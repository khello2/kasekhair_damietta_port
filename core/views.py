import requests, pytz
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum, Max, Min, F, Q, Avg, Count
from django.utils import timezone
from datetime import timedelta, datetime, time
from .models import FuelMovement, InventoryItem, NewsTicker, WorkShift, Dredger, PipeFighterOperations, Staff, DailyProjectReport, WeeklyRotation, MarineInventoryReport, MarineInventoryDetail, InventoryCategory
from django.contrib.auth.decorators import login_required

# --- دالة إغلاق التقارير القديمة تلقائياً ---
def auto_close_old_reports():
    cairo_tz = pytz.timezone('Africa/Cairo')
    now_local = timezone.now().astimezone(cairo_tz)
    today_noon = now_local.replace(hour=12, minute=0, second=0, microsecond=0)
    if now_local >= today_noon:
        DailyProjectReport.objects.filter(date_started__lt=now_local.date(), is_closed=False).update(is_closed=True)
    else:
        DailyProjectReport.objects.filter(date_started__lt=now_local.date() - timedelta(days=1), is_closed=False).update(is_closed=True)

# --- الصفحة الرئيسية ---
@login_required(login_url='/accounts/login/')
def home(request):
    auto_close_old_reports()
    dredgers = Dredger.objects.all()
    dredger_status_list = []
    cairo_tz = pytz.timezone('Africa/Cairo')
    now_local = timezone.now().astimezone(cairo_tz)
    today_date = now_local.date()
    current_rotation = WeeklyRotation.objects.order_by('-start_date').first()
    active_group = current_rotation.active_group if current_rotation else None
    staff_member = Staff.objects.filter(user=request.user).first() if request.user.is_authenticated else None
    news = NewsTicker.objects.filter(is_active=True).order_by('-created_at')

    for d in dredgers:
        all_shifts = WorkShift.objects.filter(report_24h__dredger=d).order_by('-start_time', '-id')
        last_shift = all_shifts.first()
        status_text = last_shift.get_status_display() if last_shift else "غير محدد"
        status_code = last_shift.status if last_shift else 'inactive'
        op_name = last_shift.operator.name if last_shift and last_shift.operator else "لا يوجد"
        op_phone = last_shift.operator.phone if last_shift and last_shift.operator and last_shift.operator.phone else "N/A"
        is_handed_over = not (last_shift and not last_shift.end_time)
        current_active_operator = last_shift.operator if last_shift and not last_shift.end_time else None
        is_owner = (staff_member == current_active_operator) if staff_member else False
        can_view = (request.user.is_superuser or (staff_member and staff_member.team_type == 'dredger') or (request.user in d.allowed_operators.all()))
        can_add = False
        if request.user.is_superuser: can_add = True
        elif staff_member and can_view and staff_member.group == active_group:
            if is_handed_over or is_owner: can_add = True

        current_fuel_val = 0
        if last_shift:
            current_fuel_val = last_shift.fuel_end if (last_shift.fuel_end and last_shift.fuel_end > 0) else (last_shift.fuel_start + last_shift.fuel_received)

        dredger_status_list.append({
            'object': d, 'id': d.id, 'name': d.name, 'can_view': can_view, 'can_add': can_add,
            'is_handed_over': is_handed_over, 'is_owner': is_owner, 'status_code': status_code,
            'status_text': status_text, 'op_name': op_name, 'op_phone': op_phone, 'vessel_phone': d.vessel_phone,
            'current_fuel': round(current_fuel_val, 0), 'fuel_alert': 'success' if current_fuel_val >= 10000 else 'danger',
        })

    labels, production_data = [], []
    for i in range(6, -1, -1):
        target_date = today_date - timedelta(days=i)
        day_sum = WorkShift.objects.filter(report_24h__date_started=target_date).aggregate(Sum('quantity_m3'))['quantity_m3__sum'] or 0
        labels.append(target_date.strftime('%d %b')); production_data.append(day_sum)

    return render(request, 'core/index.html', {'news': news, 'dredger_status_list': dredger_status_list, 'labels': labels, 'production_data': production_data})

# --- إجراءات سريعة (تشغيل/توقف) ---
def quick_action(request, dredger_id, action_type):
    dredger = get_object_or_404(Dredger, id=dredger_id)
    staff = Staff.objects.filter(user=request.user).first()
    now = timezone.now()
    cairo_tz = pytz.timezone('Africa/Cairo')
    now_l = now.astimezone(cairo_tz)
    report_date = now_l.date()
    if now_l.time() < time(12, 0): report_date -= timedelta(days=1)
    report, _ = DailyProjectReport.objects.get_or_create(dredger=dredger, date_started=report_date)
    prev = WorkShift.objects.filter(report_24h__dredger=dredger).order_by('-id').first()
    last_open = WorkShift.objects.filter(report_24h__dredger=dredger, end_time__isnull=True).last()

    if action_type in ['stop', 'handover'] and last_open:
        last_open.end_time = now
        last_open.save()
        return redirect(f'/admin/core/workshift/{last_open.id}/change/')

    if action_type == 'start':
        # 1. جلب آخر سجل للكراكة لسحب كافة القراءات السابقة
        prev = WorkShift.objects.filter(report_24h__dredger=dredger).order_by('-id').first()

        # 2. قفل أي وردية مفتوحة حالياً (إن وجدت)
        if last_open:
            last_open.end_time = now
            last_open.save()

        # 3. إنشاء الوردية الجديدة مع وراثة (الديزل، الساعات، الأعماق، والموقع)
        new_s = WorkShift.objects.create(
            report_24h=report,
            operator=staff,
            status='active',
            start_time=now,
            # --- وراثة منطق الأعماق الجديد (المخطط الهندسي) ---
            depth_before=prev.depth_after if prev else 0, # "قبل" للجديد هو "بعد" للقديم
            swing_width=prev.swing_width if prev else 0,
            # --- وراثة القراءات الفنية ---
            fuel_start=prev.fuel_end if prev else 0,
            main_engine_start=prev.main_engine_end if prev else 0,
            aux_engine_start=prev.aux_engine_end if prev else 0,
            # --- وراثة الموقع الجغرافي ---
            start_east=prev.end_east if prev else None,
            start_north=prev.end_north if prev else None
        )
        # التوجه لصفحة التعديل لتكملة البيانات
        return redirect(f'/admin/core/workshift/{new_s.id}/change/')

    return redirect('home')


def report_detail(request, report_id):
    report = get_object_or_404(DailyProjectReport, id=report_id)
    shifts = report.shifts.all().order_by('start_time')
    cairo_tz = pytz.timezone('Africa/Cairo')
    now = timezone.now()

    def to_hhmm(decimal_hours):
        if not decimal_hours or decimal_hours < 0: return "00:00"
        total_mins = int(round(decimal_hours * 60))
        hrs, mins = divmod(total_mins, 60)
        return f"{hrs:02d}:{mins:02d}"

    # متغيرات التجميع
    op_performance = {}
    timeline_events = []
    unique_operators = [] # لإظهار طاقم التشغيل فوق
    total_work_dec, total_stop_dec, day_main_h, day_aux_h, total_received = 0, 0, 0, 0, 0

    if shifts.exists():
        for s in shifts:
            # 1. جمع أسماء الطاقم الفريدة
            if s.operator and s.operator.name not in unique_operators:
                unique_operators.append(s.operator.name)

            # 2. تحليل الأداء لكل مشغل
            op_name = s.operator.name if s.operator else "غير محدد"
            if op_name not in op_performance:
                op_performance[op_name] = {'work': 0, 'stop': 0, 'meters': 0}

            eff_end = s.end_time if s.end_time else now
            dur = (eff_end - s.start_time).total_seconds() / 3600 if s.start_time else 0

            # تجميع الأمتار لكل مشغل أياً كانت حالة الوردية لضمان عدم ظهور 0
            op_performance[op_name]['meters'] += (s.progress_meters or 0)

            if s.status == 'active':
                op_performance[op_name]['work'] += dur
                total_work_dec += dur
            else:
                op_performance[op_name]['stop'] += dur
                total_stop_dec += dur

            # 3. تجميع الساعات العامة والسولار
            day_main_h += (s.main_engine_hours or 0)
            day_aux_h += (s.aux_engine_hours or 0)
            total_received += (s.fuel_received or 0)

            # 4. بناء التايم لاين
            st_l = s.start_time.astimezone(cairo_tz)
            en_l = eff_end.astimezone(cairo_tz)
            timeline_events.append({
                'time_range': f"{st_l.strftime('%H:%M')} - {en_l.strftime('%H:%M') if s.end_time else 'الآن'}",
                'description': s.get_status_display() + (f" : {s.stop_reason}" if s.stop_reason else ""),
                'status': s.status,
                'duration_str': to_hhmm(dur)
            })

    # تجهيز جدول الأداء الفعلي (performance_table)
    performance_table = []
    for name, data in op_performance.items():
        # المعدل = الأمتار ÷ ساعات التشغيل الفعلية
        rate = round(data['meters'] / data['work'], 2) if data['work'] > 0.1 else 0
        performance_table.append({
            'operator': name,
            'work_time_str': to_hhmm(data['work']),
            'stop_time_str': to_hhmm(data['stop']),
            'meters': data['meters'], # الأمتار الحقيقية لكل مشغل
            'rate': rate
        })

    # حسابات الكروت
    first_s = shifts.first()
    last_s = shifts.last()
    day_start_fuel = first_s.fuel_start if first_s else 0
    day_end_fuel = last_s.fuel_end if (last_s and last_s.fuel_end > 0) else 0
    usage = (day_start_fuel + total_received) - day_end_fuel if day_end_fuel > 0 else 0
    last_with_coords = shifts.exclude(end_east__isnull=True).last() or last_s

    context = {
        'report': report,
        'performance_table': performance_table,
        'timeline': timeline_events,
        'unique_operators': unique_operators, # رجعنا طاقم التشغيل
        'total_m3': sum(s.quantity_m3 for s in shifts),
        'total_meters': sum(s.progress_meters for s in shifts),
        'total_work_hours': to_hhmm(total_work_dec),
        'total_stop_hours': to_hhmm(total_stop_dec),
        'total_received': total_received,
        'fuel_start_val': day_start_fuel,
        'fuel_end_val': day_end_fuel,
        'total_fuel_usage': round(usage, 2),
        'main_engine': {'start': first_s.main_engine_start if first_s else 0, 'end': last_s.main_engine_end if (last_s and last_s.main_engine_end > 0) else (first_s.main_engine_start if first_s else 0), 'net': to_hhmm(day_main_h)},
        'aux_engine': {'start': first_s.aux_engine_start if first_s else 0, 'end': last_s.aux_engine_end if (last_s and last_s.aux_engine_end > 0) else (first_s.aux_engine_start if first_s else 0), 'net': to_hhmm(day_aux_h)},
        'start_coords': {'east': first_s.start_east if first_s else "0.0", 'north': first_s.start_north if first_s else "0.0"},
        'end_coords': {'east': last_with_coords.end_east if last_with_coords else "0.0", 'north': last_with_coords.end_north if last_with_coords else "0.0"},
        'floating_line': last_s.floating_line if last_s else 0,
        'land_line': last_s.land_line if last_s else 0,
        'total_line': (last_s.floating_line or 0) + (last_s.land_line or 0) if last_s else 0,
    }
    return render(request, 'core/report_detail.html', context)

def fuel_report(request):
    # حسابات ميزان السولار
    marine_in = FuelMovement.objects.filter(destination_equipment__category='marine', move_type='in').aggregate(Sum('amount'))['amount__sum'] or 0
    marine_out = FuelMovement.objects.filter(source='multicat_tank').aggregate(Sum('amount'))['amount__sum'] or 0

    admin_in = FuelMovement.objects.filter(source='truck', move_type='in').filter(Q(notes__icontains='خزان') | Q(source='truck')).aggregate(Sum('amount'))['amount__sum'] or 0
    admin_out = FuelMovement.objects.filter(source='admin_tank').aggregate(Sum('amount'))['amount__sum'] or 0

    # جلب آخر 20 حركة لعرضها في الجدول
    movements = FuelMovement.objects.all().order_by('-date')[:20]

    context = {
        'multicat_balance': marine_in - marine_out,
        'admin_tank_balance': admin_in - admin_out,
        'marine_in': marine_in,
        'marine_out': marine_out,
        'admin_in': admin_in,
        'admin_out': admin_out,
        'movements': movements, # تأكد إن الاسم 'movements' مطابق للي في الـ HTML
    }
    return render(request, 'core/fuel_report.html', context)

@login_required
def analytics(request):
    from .models import WorkShift, Staff, Dredger
    from django.utils import timezone
    from datetime import datetime, timedelta
    import pytz

    cairo_tz = pytz.timezone('Africa/Cairo')
    now_local = timezone.now().astimezone(cairo_tz)

    # 1. جلب كافة الكراكات المتاحة بالسيستم لعرضها في القائمة المنسدلة للفرز
    all_dredgers = Dredger.objects.all()

    # 2. استقبال معرف الكراكة المستهدفة من الرابط
    dredger_id = request.GET.get('dredger_id')
    current_dredger = None
    if dredger_id:
        try:
            current_dredger = Dredger.objects.filter(id=int(dredger_id)).first()
        except (ValueError, TypeError):
            pass
    
    # حماية الأمان: لو مفيش كراكة ممررة بالرابط، السيستم يلقط أول كراكة مسجلة تلقائياً
    if not current_dredger:
        current_dredger = Dredger.objects.first()

    # 3. استقبال تواريخ الفلتر الديناميكي الحر
    start_date_raw = request.GET.get('start_date')
    end_date_raw = request.GET.get('end_date')

    if start_date_raw and end_date_raw:
        try:
            start_date = datetime.strptime(start_date_raw, '%Y-%m-%d').replace(hour=0, minute=0, second=0).astimezone(cairo_tz)
            end_date = datetime.strptime(end_date_raw, '%Y-%m-%d').replace(hour=23, minute=59, second=59).astimezone(cairo_tz)
        except ValueError:
            start_date = now_local - timedelta(days=30)
            end_date = now_local
    else:
        start_date = now_local - timedelta(days=30)
        end_date = now_local

    # 4. محرك الفرز الفولاذي: جلب ورديات الفترة المحددة وتصفيتها إجبارياً بحسب الكراكة النشطة لمنع تداخل الداتا
    if current_dredger:
        target_shifts = WorkShift.objects.filter(
            start_time__gte=start_date, 
            start_time__lte=end_date,
            report_24h__dredger=current_dredger  # الربط الصارم عبر تقرير الـ 24 ساعة المجمع
        )
    else:
        target_shifts = WorkShift.objects.none()

    total_m3_period = 0
    total_meters_period = 0
    total_fuel_period = 0
    
    op_stats = {}
    shift_battle = {
        'A': {'m3': 0, 'meters': 0, 'work_h': 0, 'stops': 0, 'fuel': 0, 'shifts_count': 0},
        'B': {'m3': 0, 'meters': 0, 'work_h': 0, 'stops': 0, 'fuel': 0, 'shifts_count': 0}
    }

    for s in target_shifts:
        m3_val = float(s.quantity_m3 or 0)
        if m3_val == 0 and s.depth_after > 0:
             m3_val = abs(s.depth_after - s.depth_before) * (s.progress_meters or 0) * (s.swing_width or 0)

        meters_val = float(s.progress_meters or 0)
        fuel_val = float(s.fuel_usage or 0)

        total_m3_period += m3_val
        total_meters_period += meters_val
        total_fuel_period += fuel_val

        name = s.operator.name if s.operator else "مشغل غير محدد"
        group = s.operator.group if s.operator else 'غير محدد'
        
        if name not in op_stats:
            op_stats[name] = {'m3': 0, 'meters': 0, 'work_h': 0, 'stops_h': 0, 'fuel': 0, 'group': group, 'count': 0}

        op_stats[name]['m3'] += m3_val
        op_stats[name]['meters'] += meters_val
        op_stats[name]['fuel'] += fuel_val
        op_stats[name]['count'] += 1

        if group in shift_battle:
            shift_battle[group]['m3'] += m3_val
            shift_battle[group]['meters'] += meters_val
            shift_battle[group]['fuel'] += fuel_val
            shift_battle[group]['shifts_count'] += 1

        end_t = s.end_time if s.end_time else timezone.now()
        dur = (end_t - s.start_time).total_seconds() / 3600

        if s.status == 'active':
            op_stats[name]['work_h'] += dur
            if group in shift_battle: shift_battle[group]['work_h'] += dur
        else:
            op_stats[name]['stops_h'] += dur
            if group in shift_battle: shift_battle[group]['stops'] += dur

    operators_ranking = []
    for op_name, data in op_stats.items():
        rate = round(data['m3'] / data['work_h'], 2) if data['work_h'] > 0.1 else 0
        contribution = round((data['m3'] / total_m3_period * 100), 1) if total_m3_period > 0 else 0
        fuel_per_m3 = round(data['fuel'] / data['m3'], 2) if data['m3'] > 0 else 0

        operators_ranking.append({
            'name': op_name, 'm3': round(data['m3'], 1), 'meters': round(data['meters'], 1),
            'work_h': round(data['work_h'], 1), 'stops_h': round(data['stops_h'], 1),
            'rate': rate, 'fuel_per_m3': fuel_per_m3, 'contribution': contribution, 'group': data['group']
        })
    operators_ranking = sorted(operators_ranking, key=lambda x: (x['m3'], x['rate']), reverse=True)

    final_battle = []
    for g_name, g_data in shift_battle.items():
        fuel_rate = round(g_data['fuel'] / g_data['m3'], 2) if g_data['m3'] > 0 else 0
        final_battle.append({
            'name': g_name, 'm3': round(g_data['m3'], 1), 'meters': round(g_data['meters'], 1),
            'work_h': round(g_data['work_h'], 1), 'stops': round(g_data['stops'], 1),
            'fuel': round(g_data['fuel'], 1), 'fuel_rate': fuel_rate, 'shifts_count': g_data['shifts_count']
        })

    status_map = {
        'breakdown_mech': 'عطل ميكانيكي', 'breakdown_elec': 'عطل كهربائي', 'breakdown_hydrulic': 'عطل هيدروليك',
        'welding': 'أعمال لحام', 'maintenance': 'صيانة دورية / عمرة', 'anchors': 'نقل مخاطيف',
        'maneuver': 'مناورة / تغيير موقع', 'pipeline': 'فك / تركيب / إصلاح خط الطرد',
        'weather': 'توقف بسبب سوء الأحوال الجوية', 'waiting_barge': 'انتظار صندل / تموين',
        'safety': 'توقف لأسباب تتعلق بالسلامة', 'inspection': 'تفتيش / زيارة رسمية',
        'handover': 'استلام وتسليم وردية', 'obstruction': 'عوائق بالتربة', 'other': 'توقف لأسباب أخرى'
    }
    
    stop_analysis = []
    for g in ['A', 'B']:
        items = []
        g_stops = target_shifts.filter(operator__group=g).exclude(status='active')
        for s_code, s_name in status_map.items():
            qs = g_stops.filter(status=s_code)
            if qs.exists():
                hrs = sum(((rs.end_time if rs.end_time else timezone.now()) - rs.start_time).total_seconds() / 3600 for rs in qs)
                items.append({'name': s_name, 'count': qs.count(), 'hours': round(hrs, 1)})
        stop_analysis.append({'group': g, 'items': items})

    context = {
        'total_m3': round(total_m3_period, 1), 'total_meters': round(total_meters_period, 1), 'total_fuel': round(total_fuel_period, 1),
        'month_start': start_date.strftime('%Y-%m-%d'), 'month_end': end_date.strftime('%Y-%m-%d'),
        'operators_ranking': operators_ranking, 'stop_analysis': stop_analysis, 'final_battle': final_battle,
        'all_dredgers': all_dredgers,          # ممرر لبناء القائمة المنسدلة
        'current_dredger': current_dredger,    # الكراكة النشطة الحالية للفرز
    }
    return render(request, 'core/analytics.html', context)


@login_required
def inventory_print(request):
    from .models import InventoryItem
    all_items = InventoryItem.objects.filter(assign_to__in=['site', 'all']).order_by('category', 'id')

    categorized = {}
    for item in all_items:
        # قراءة رصيد البر المخصص في الطباعة الرسمية
        item.quantity_found = item.quantity_site
        if item.category not in categorized:
            categorized[item.category] = []
        categorized[item.category].append(item)

    return render(request, 'core/inventory_print_official.html', {
        'categorized_data': categorized,
        'date': timezone.now()
    })

@login_required
def pipe_report_detail(request, report_id):
    from .models import PipeFighterOperations, InventoryItem
    from django.shortcuts import render, get_object_or_404
    from django.utils import timezone

    # 1. جلب التقرير الأساسي (الأطوال وإحصائيات الخط بالخدمة)
    report = get_object_or_404(PipeFighterOperations, id=report_id)

    # 2. جلب كافة الأصناف المفعلة للخط (القديمة والجديدة اليدوية)
    all_items = InventoryItem.objects.filter(show_in_pipe=True).order_by('category', 'id')

    categorized_data = {}
    for item in all_items:
        # قراءة الأرصدة الحقيقية للخط لمنع نزولها أصفار
        item.quantity_found = item.quantity_pipe

        cat = item.category if item.category else "مهمات عامة"
        # عزل قسم الاستوك وقسم أخرى عن الجداول المتغيرة
        if cat == "الاستوك" or cat == "أخرى":
            continue

        if cat not in categorized_data:
            categorized_data[cat] = []
        categorized_data[cat].append(item)

    # 3. سحب أرصدة الاستوك الحقيقية أوتوماتيكياً من جدول المخزن لعرضها في الجدول المخصص
    stock_data = {
        'pipes_new': InventoryItem.objects.filter(name__icontains='مواسير جديدة').first(),
        'pipes_used': InventoryItem.objects.filter(name__icontains='مواسير مستعملة').first(),
        'pipes_scrap': InventoryItem.objects.filter(name__icontains='مواسير هالك').first(),

        'rubbers_new': InventoryItem.objects.filter(name__icontains='ربرات جديدة').first(),
        'rubbers_used': InventoryItem.objects.filter(name__icontains='ربرات مستعملة').first(),
        'rubbers_scrap': InventoryItem.objects.filter(name__icontains='ربرات هالك').first(),
        'pontoons_new': InventoryItem.objects.filter(name__icontains='طوافات جديدة').first(),
        'pontoons_used': InventoryItem.objects.filter(name__icontains='طوافات مستعملة').first(),
        'pontoons_scrap': InventoryItem.objects.filter(name__icontains='طوافات هالك').first(),
    }

    # تأكيد تمرير البيانات كاملة لملف الـ HTML
    return render(request, 'core/pipe_report_detail.html', {
        'report': report,
        'categorized_data': categorized_data,
        'stock': stock_data,
        'date': timezone.now()
    })


def reports_list(request):
    # جلب كافة تقارير الكراكات
    all_reports = DailyProjectReport.objects.all().order_by('-date_started')

    # جلب كافة تقارير البايب فايتر
    pipe_reports = PipeFighterOperations.objects.all().order_by('-date')

    # اطبع العدد في الـ Console عشان تتأكد إن فيه بيانات (للمطور فقط)
    print(f"عدد تقارير الكراكات: {all_reports.count()}")

    context = {
        'reports': all_reports,    # تأكد إن الاسم 'reports' (جمع)
        'pipe_ops': pipe_reports   # تأكد إن الاسم 'pipe_ops'
    }
    return render(request, 'core/reports_list.html', context)
# core/views.py
from django.shortcuts import render

def error_404(request, exception):
    return render(request, '404.html', status=404)

def error_403(request, exception=None):
    return render(request, '403.html', status=403)


def print_marine_inventory(request, report_id):
    from .models import MarineInventoryReport
    from django.shortcuts import get_object_or_404, render
    
    # جلب التقرير متضمناً الكراكة والمسؤول لمنع أي أخطاء في الطباعة
    report = get_object_or_404(MarineInventoryReport, id=report_id)

    # ترتيب الأصناف المجرودة داخل جدول الطباعة
    details = report.details.all().order_by('category', 'item_name')

    # تقسيم البيانات للطباعة حسب القسم
    categorized_data = {}
    for d in details:
        cat = d.category
        if cat not in categorized_data:
            categorized_data[cat] = []
        categorized_data[cat].append(d)

    return render(request, 'core/marine_inventory_print.html', {
        'report': report,
        'categorized_data': categorized_data,
        'details': details  
    })

def marine_inventory_list(request):
    from .models import MarineInventoryReport
    from django.shortcuts import render
    
    # سحب كافة التقارير التاريخية وعرض الكراكة التابعة لها في جدول الأرشيف الموحد
    reports = MarineInventoryReport.objects.all().order_by('-date')
    return render(request, 'core/marine_inventory_list.html', {'reports': reports})

@login_required
def site_inventory_view(request):
    from .models import InventoryItem, MarineInventoryReport
    from django.utils import timezone
    from django.shortcuts import render

    # 1. جلب آخر تقرير جرد تم تسجيله للموقع (البر) لسحب التاريخ والمسؤول منه
    last_report = MarineInventoryReport.objects.filter(report_type='site').order_by('-date', '-id').first()

    # 2. جلب الأصناف المخصصة للبر
    all_items = InventoryItem.objects.filter(show_in_site=True).order_by('category', 'id')

    categorized = {}
    for item in all_items:
        # قراءة الأرصدة الحقيقية للبر
        item.quantity = item.quantity_site

        if item.category not in categorized:
            categorized[item.category] = []
        categorized[item.category].append(item)

    return render(request, 'core/site_inventory_hub.html', {
        'categorized_items': categorized,
        'report': last_report, # بعتنا التقرير عشان يسحب الاسم والتاريخ
        'date': timezone.now()
    })


@login_required
def start_marine_inventory(request):
    from .models import InventoryItem, MarineInventoryReport, MarineInventoryDetail, Staff, Dredger
    from django.utils import timezone
    from django.shortcuts import render, redirect

    # 1. لقط الكراكة من الـ GET أو الـ POST لضمان عدم ضياع الهوية الفنية للمعدّة أثناء الحفظ
    dredger_id = request.GET.get('dredger_id') or request.POST.get('dredger_id')
    current_dredger = None
    
    if dredger_id:
        try:
            current_dredger = Dredger.objects.filter(id=int(dredger_id)).first()
        except (ValueError, TypeError):
            pass
            
    # حركة أمان فنية حاسمة: لو المشغل فتح الصفحة مباشرة بدون رابط، يقرأ الكراكة الأولى
    if not current_dredger:
        current_dredger = Dredger.objects.first()

    # تأمين الموظف المسؤول لتفادي الـ IntegrityError
    staff = Staff.objects.filter(user=request.user).first() or Staff.objects.first()
    if not staff:
        from django.contrib.auth.models import User
        admin_user = User.objects.filter(is_superuser=True).first()
        staff = Staff.objects.create(user=admin_user, name="مدير النظام")

    # 2. جلب أصناف الكراكة بناءً على نظام المربعات المعزول (show_in_marine=True)
    raw_items = InventoryItem.objects.filter(show_in_marine=True).order_by('id')

    # تنظيف الأصناف المكررة في العرض الفوري
    all_items = []
    seen_names = set()
    for item in raw_items:
        clean_name = item.name.strip().lower()
        if clean_name not in seen_names:
            item.current_qty = item.quantity_marine
            all_items.append(item)
            seen_names.add(clean_name)

    if request.method == "POST":
        # 3. فرض الحفظ الإجباري المباشر لاسم الكراكة الحقيقية في التقرير لمنع اللجوء للديفولت
        report = MarineInventoryReport.objects.create(
            operator=staff,
            report_type='marine',
            notes=request.POST.get('notes', ''),
            dredger=current_dredger  # الحقن المباشر في قاعدة البيانات
        )

        # 4. حفظ وتحديث أرصدة البحرية المخصصة فقط (quantity_marine)
        for item in all_items:
            qty_raw = request.POST.get(f'qty_{item.id}')
            if qty_raw is not None and qty_raw.strip() != "":
                try:
                    qty_val = float(qty_raw)
                    InventoryItem.objects.filter(id=item.id).update(quantity_marine=qty_val)
                    MarineInventoryDetail.objects.create(
                        report=report, item_name=item.name, category=item.category, quantity_found=qty_val
                    )
                except Exception: continue

        # 5. إضافة الأصناف الجديدة يدوياً وتثبيتها بختم ظهور الكراكة
        new_names = request.POST.getlist('new_item_name[]')
        new_qtys = request.POST.getlist('new_item_qty[]')
        new_cats = request.POST.getlist('new_item_cat[]')

        for name, qty, cat_name in zip(new_names, new_qtys, new_cats):
            clean_name = name.strip()
            if clean_name:
                qty_val = float(qty or 0)
                existing = InventoryItem.objects.filter(name__iexact=clean_name, category=cat_name).first()

                if existing:
                    InventoryItem.objects.filter(id=existing.id).update(quantity_marine=qty_val)
                    MarineInventoryDetail.objects.create(report=report, item_name=existing.name, category=cat_name, quantity_found=qty_val)
                else:
                    InventoryItem.objects.create(
                        name=clean_name,
                        category=cat_name,
                        show_in_marine=True,
                        quantity_marine=qty_val,
                    )
                    MarineInventoryDetail.objects.create(report=report, item_name=clean_name, category=cat_name, quantity_found=qty_val)

        return redirect('marine_inventory_list')

    # 6. تنظيم العرض للأقسام في الـ HTML
    categorized_items = {}
    for item in all_items:
        if item.category not in categorized_items:
            categorized_items[item.category] = []
        categorized_items[item.category].append(item)

    return render(request, 'core/marine_inventory_form.html', {
        'categorized_items': categorized_items,
        'current_dredger': current_dredger,  
        'date': timezone.now()
    })

@login_required
def pipe_report_create(request):
    # 1. الذاكرة الذكية: جلب آخر تقرير عشان الخانات متكنش فاضية
    last_report = PipeFighterOperations.objects.order_by('-date').first()

    # 2. قائمة الطوافات الجديدة (القسم المستقل)
    pontoons_list = ["طوافة 22", "طوافة 18", "طوافة فيبر"]

    if request.method == "POST":
        staff = Staff.objects.filter(user=request.user).first()
        # هنا السيستم هيخلق التقرير
        report = PipeFighterOperations.objects.create(
            operator_in_charge=staff,
            notes=request.POST.get('notes', ''),
            # أضف هنا باقي الحقول اللي في موديل PipeFighterOperations بتاعك
        )
        messages.success(request, "تم تسجيل تقرير الخط وتحديث الأرصدة.")
        return redirect('home')

    return render(request, 'core/pipe_report_form.html', {
        'last_report': last_report,
        'pontoons_list': pontoons_list,
        'date': timezone.now()
    })
@login_required
def pipefighter_report(request):
    from .models import PipeFighterOperations, Staff

    # 1. جلب آخر تقرير مسجل لسحب البيانات منه
    last_report = PipeFighterOperations.objects.order_by('-date').first()

    if request.method == "POST":
        staff = Staff.objects.filter(user=request.user).first()
        # كود الحفظ العادي بتاعك هنا...
        # ...
        return redirect('home')

    # نرسل التقرير الأخير للـ template
    return render(request, 'core/pipe_report_form.html', {
        'last_report': last_report,
        'date': timezone.now()
    })

@login_required
def pipefighter_form_view(request):
    from .models import PipeFighterOperations, Staff, InventoryItem
    from django.utils import timezone
    from django.contrib import messages
    from django.shortcuts import render, redirect

    # تأمين الموظف المسؤول لتفادي الـ IntegrityError نهائياً
    staff = Staff.objects.filter(user=request.user).first() or Staff.objects.first()
    if not staff:
        from django.contrib.auth.models import User
        admin_user = User.objects.filter(is_superuser=True).first()
        staff = Staff.objects.create(user=admin_user, name="مدير النظام")

    # 1. الذاكرة الذكية للحقول الثابتة لخط الطرد (سحب آخر وردية مسجلة)
    last = PipeFighterOperations.objects.order_by('-date', '-id').first()

    # 2. جلب الأصناف المخصصة للخط بناءً على نظام المربعات المطور (show_in_pipe=True)
    raw_items = InventoryItem.objects.filter(show_in_pipe=True).order_by('id')

    if not raw_items.exists():
        raw_items = InventoryItem.objects.all()[:10]

    pipe_items_final = []
    seen_names = set()
    for item in raw_items:
        clean_name = item.name.strip().lower()
        if clean_name not in seen_names:
            # تمرير رصيد الخط المستقل والمعزول تماماً ليعرض كـ (المتاح حالياً)
            item.current_qty = item.quantity_pipe
            pipe_items_final.append(item)
            seen_names.add(clean_name)

    if request.method == "POST":
        def to_int(val):
            try: return int(val) if val else 0
            except: return 0

        # 3. إنشاء التقرير وحفظ جميع حقول الاستوك الـ 9 بدقة وبأرقامها الحقيقية لمنع نزولها أصفار
        report = PipeFighterOperations.objects.create(
            operator_in_charge=staff,
            shift=request.POST.get('shift', 'morning'),

            # أ- إحصائيات الخط العائم والأرضي بالخدمة
            float_pipes=to_int(request.POST.get('float_pipes')),
            float_rubbers=to_int(request.POST.get('float_rubbers')),
            float_pontoons=to_int(request.POST.get('float_pontoons')),
            float_pantons=to_int(request.POST.get('float_pantons')),  # حقل البانتون
            float_anchors=to_int(request.POST.get('float_anchors')),
            land_pipes=to_int(request.POST.get('land_pipes')),
            land_rubbers=to_int(request.POST.get('land_rubbers')),

            # ب- حقول جرد الاستوك والمخزن العام (خارج الخدمة)
            stock_pipes_new=to_int(request.POST.get('stock_pipes_new')),
            stock_pipes_used=to_int(request.POST.get('stock_pipes_used')),
            stock_pipes_scrap=to_int(request.POST.get('stock_pipes_scrap')),
            stock_rubbers_new=to_int(request.POST.get('stock_rubbers_new')),
            stock_rubbers_used=to_int(request.POST.get('stock_rubbers_used')),
            stock_rubbers_scrap=to_int(request.POST.get('stock_rubbers_scrap')),
            stock_pontoons_new=to_int(request.POST.get('stock_pontoons_new')),
            stock_pontoons_used=to_int(request.POST.get('stock_pontoons_used')),
            stock_pontoons_scrap=to_int(request.POST.get('stock_pontoons_scrap')),

            # ج- حقول المهمات والأدوات والعدد (مراجعة وتطابق 100% مع الفورم)
                        # ج- حقول المهمات والأدوات والعدد (تأمين الحفظ والربط 100% مع الـ HTML)
            bolts_30=to_int(request.POST.get('bolts_30')),
            bolts_27=to_int(request.POST.get('bolts_27')),
            bolts_24=to_int(request.POST.get('bolts_24')),

            wrench_30=to_int(request.POST.get('wrench_30')),
            wrench_27=to_int(request.POST.get('wrench_27')),
            wrench_24=to_int(request.POST.get('wrench_24')),

            socket_30=to_int(request.POST.get('socket_30')),
            socket_27=to_int(request.POST.get('socket_27')),
            socket_24=to_int(request.POST.get('socket_24')),

            air_gun=to_int(request.POST.get('air_gun')),

            # د- بيان الأعمال والملاحظات
            work_description=request.POST.get('work_description', '')

        )

        # 4. تحديث رصيد الخط المنفصل للأصناف الموجودة (quantity_pipe)
        for item in pipe_items_final:
            qty_raw = request.POST.get(f'qty_{item.id}')
            if qty_raw is not None and qty_raw.strip() != "":
                try:
                    InventoryItem.objects.filter(id=item.id).update(quantity_pipe=float(qty_raw))
                except Exception: continue

        # 5. إضافة الأصناف الجديدة يدوياً وتثبيتها للأبد بختم البايب فيتر المطور بكسر شرط الـ NOT NULL إجبارياً
        new_names = request.POST.getlist('new_item_name[]')
        new_qtys = request.POST.getlist('new_item_qty[]')
        new_cats = request.POST.getlist('new_item_cat[]')

        for name, qty, cat_name in zip(new_names, new_qtys, new_cats):
            clean_n = name.strip()
            if clean_n:
                qty_val = float(qty or 0)
                existing = InventoryItem.objects.filter(name__iexact=clean_n, category=cat_name).first()
                if existing:
                    InventoryItem.objects.filter(id=existing.id).update(quantity_pipe=qty_val)
                else:
                    # تغذية حقل quantity إجبارياً هنا لحل الـ IntegrityError فوراً وكسر جمود SQLite بالسيرفر
                    InventoryItem.objects.create(
                        name=clean_n,
                        category=cat_name,
                        show_in_pipe=True,
                        quantity_pipe=qty_val,
                    )

        # تشغيل المحرك الهندسي لحساب الأطوال الإجمالية فوراً قبل التحويل للطباعة
        report.save()
        messages.success(request, "تم حفظ تقرير الخط بنجاح.")
        # التحويل الفوري لصفحة المعاينة والطباعة المترتبة بالمسطرة
        return redirect('pipe_report_detail', report_id=report.id)

    # 6. تنظيم الأصناف في أقسام للعرض وطرد قسم أخرى والاستوك من الـ Loop الديناميكي لعدم الزحمة
    categorized_items = {}
    for item in pipe_items_final:
        cat = item.category if item.category else "مهمات عامة"
        if cat == "أخرى" or cat == "الاستوك":
            continue
        if cat not in categorized_items:
            categorized_items[cat] = []
        categorized_items[cat].append(item)

    return render(request, 'core/pipe_report_form.html', {
        'last': last,
        'categorized_items': categorized_items,
        'date': timezone.now()
    })

@login_required
def site_inventory_entry(request):
    from .models import InventoryItem, MarineInventoryReport, MarineInventoryDetail, Staff
    from django.utils import timezone
    from django.shortcuts import render, redirect

    staff = Staff.objects.filter(user=request.user).first() or Staff.objects.first()
    if not staff:
        from django.contrib.auth.models import User
        admin_user = User.objects.filter(is_superuser=True).first()
        staff = Staff.objects.create(user=admin_user, name="مدير النظام")

    # 1. التعديل: الفلترة بناءً على مربع اختيار البر (show_in_site=True)
    raw_items = InventoryItem.objects.filter(show_in_site=True).order_by('id')

    all_items = []
    seen_names = set()
    for item in raw_items:
        clean_name = item.name.strip().lower()
        if clean_name not in seen_names:
            item.current_qty = item.quantity_site
            all_items.append(item)
            seen_names.add(clean_name)

    if request.method == "POST":
        report = MarineInventoryReport.objects.create(
            operator=staff, report_type='site', notes=request.POST.get('notes', '')
        )

        # 2. حفظ الأصناف الحالية وتحديث رصيد البر المنفصل
        for item in all_items:
            qty_raw = request.POST.get(f'qty_{item.id}')
            if qty_raw is not None and qty_raw.strip() != "":
                try:
                    qty_val = float(qty_raw)
                    InventoryItem.objects.filter(id=item.id).update(quantity_site=qty_val)
                    MarineInventoryDetail.objects.create(
                        report=report, item_name=item.name, category=item.category, quantity_found=qty_val
                    )
                except Exception: continue

        # 3. إضافة الأصناف الجديدة وتثبيتها للأبد بختم البر المطور
        new_names = request.POST.getlist('new_item_name[]')
        new_qtys = request.POST.getlist('new_item_qty[]')
        new_cats = request.POST.getlist('new_item_cat[]')

        for name, qty, cat_name in zip(new_names, new_qtys, new_cats):
            clean_name = name.strip()
            if clean_name:
                existing = InventoryItem.objects.filter(name__iexact=clean_name, category=cat_name).first()
                qty_val = float(qty or 0)

                if existing:
                    InventoryItem.objects.filter(id=existing.id).update(quantity_site=qty_val)
                    MarineInventoryDetail.objects.create(report=report, item_name=existing.name, category=cat_name, quantity_found=qty_val)
                else:
                    # التعديل: تفعيل المربع الجديد للبر عند الإنشاء اليدوي
                   InventoryItem.objects.create(
                        name=clean_name,
                        category=cat_name,
                        show_in_site=True,
                        quantity_site=qty_val,
                    )
        return redirect('site_inventory_view')

    # 4. تنظيم العرض للأقسام
    categorized_items = {}
    for item in all_items:
        if item.category not in categorized_items:
            categorized_items[item.category] = []
        categorized_items[item.category].append(item)

    return render(request, 'core/site_inventory_form.html', {
        'categorized_items': categorized_items,
        'date': timezone.now()
    })


def marine_inventory_list(request):
    # جلب تقارير الكراكة فقط
    reports = MarineInventoryReport.objects.filter(report_type='marine').order_by('-date')
    return render(request, 'core/marine_inventory_list.html', {'reports': reports})

