import pytz
from datetime import time, timedelta, datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.utils.timezone import localtime
from django.db.models import Sum, Q
from .models import DailyProjectReport, WorkShift, Staff, Dredger, FuelMovement, WeeklyRotation, NewsTicker, PipeFighterOperations, InventoryItem

@login_required(login_url='/accounts/login/')
def home(request):
    # تشغيل قفل التقارير تلقائياً لو عندك الدالة دي
    if 'auto_close_old_reports' in globals():
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
        all_shifts = WorkShift.objects.filter(report_24h__dredger=d).order_by('-id')
        last_shift = all_shifts.first()
        
        status_text = last_shift.get_status_display() if last_shift else "غير محدد"
        status_code = last_shift.status if last_shift else 'inactive'
        op_name = last_shift.operator.name if last_shift and last_shift.operator else "لا يوجد"
        op_phone = last_shift.operator.phone if last_shift and last_shift.operator and last_shift.operator.phone else "N/A"
        
        # 🛡️ الحسم البرمجي لربط العهدة: الفحص بالرمز البرمجي المعتمد 'handover' في قاعدة البيانات
        if last_shift and last_shift.status == 'handover':
            is_handed_over = True
        else:
            is_handed_over = False

        current_active_operator = last_shift.operator if last_shift else None
        is_owner = (staff_member == current_active_operator) if staff_member and current_active_operator else False
        
        can_view = (request.user.is_superuser or (staff_member and staff_member.team_type == 'dredger') or (request.user in d.allowed_operators.all()))
        can_add = False
        
        if request.user.is_superuser: 
            can_add = True
        elif staff_member and can_view and staff_member.group == active_group:
            if is_handed_over or is_owner: 
                can_add = True

        current_fuel_val = 0.0
        if last_shift:
            current_fuel_val = last_shift.fuel_end if (last_shift.fuel_end and last_shift.fuel_end > 0) else (last_shift.fuel_start or 0.0)

        dredger_status_list.append({
            'object': d, 'id': d.id, 'name': d.name, 'can_view': can_view, 'can_add': can_add,
            'is_handed_over': is_handed_over, 'is_owner': is_owner, 
            'status_code': status_code,
            'status_text': status_text, 'op_name': op_name, 'op_phone': op_phone, 'vessel_phone': d.vessel_phone,
            'current_fuel': round(current_fuel_val, 0), 'fuel_alert': 'success' if current_fuel_val >= 10000 else 'danger',
        })

    labels, production_data = [], []
    for i in range(6, -1, -1):
        target_date = today_date - timedelta(days=i)
        day_sum = WorkShift.objects.filter(report_24h__date_started=target_date).aggregate(Sum('quantity_m3'))['quantity_m3__sum'] or 0.0
        labels.append(target_date.strftime('%d %b'))
        production_data.append(day_sum)

    return render(request, 'core/index.html', {'news': news, 'dredger_status_list': dredger_status_list, 'labels': labels, 'production_data': production_data})

@login_required
def report_detail(request, report_id):
    # 🚀 هندسة السرعة الفائقة: جلب الجداول المرتبطة دفعة واحدة لمنع التقل نهائياً
    report = get_object_or_404(DailyProjectReport.objects.select_related('dredger'), id=report_id)
    shifts = report.shifts.all().select_related('operator__user').order_by('start_time')
    cairo_tz = pytz.timezone('Africa/Cairo')
    now = timezone.now()

    def to_hhmm(decimal_hours):
        if not decimal_hours or decimal_hours < 0: return "00:00"
        total_mins = int(round(decimal_hours * 60))
        hrs, mins = divmod(total_mins, 60)
        return f"{hrs:02d}:{mins:02d}"

    op_performance = {}
    timeline_events = []
    unique_operators = [] 
    total_work_dec, total_stop_dec, day_main_h, day_aux_h, total_received = 0.0, 0.0, 0.0, 0.0, 0.0

    if shifts.exists():
        for s in shifts:
            # 🚫 1. حارس التقرير الفولاذي: طرد جلسات تسليم العهدة نهائياً ومنعها من دخول الحسابات أو التايم لاين
            if s.status in ['handover', 'استلام وتسليم وردية']:
                continue # تخطي السجل فوراً والانتقال للحركة التالية

            if s.operator and s.operator.name not in unique_operators:
                unique_operators.append(s.operator.name)

            op_name = s.operator.name if s.operator else "غير محدد"
            if op_name not in op_performance:
                op_performance[op_name] = {'work': 0.0, 'stop': 0.0, 'meters': 0.0}

            eff_end = s.end_time if s.end_time else now
            dur = (eff_end - s.start_time).total_seconds() / 3600 if s.start_time else 0.0

            op_performance[op_name]['meters'] += float(s.progress_meters or 0.0)

            # 🛡️ الفرز المشترك المطور: يقرأ الرمز البرمجي المعياري أو النص القديم لربط كروت التقارير فوق صح
            is_active = (s.status == 'active' or s.status == 'تشغيل فعلي (إنتاج)')
            if is_active:
                op_performance[op_name]['work'] += dur
                total_work_dec += dur
            else:
                op_performance[op_name]['stop'] += dur
                total_stop_dec += dur

            day_main_h += float(s.main_engine_hours or 0.0)
            day_aux_h += float(s.aux_engine_hours or 0.0)
            total_received += float(s.fuel_received or 0.0)

            st_l = s.start_time.astimezone(cairo_tz)
            en_l = eff_end.astimezone(cairo_tz)
            
            # 🗺️ الـمـقـص والـلـحـام الـزمـنـي الـذكـي لـتـسـلـسـل الأحـداث بالأسفل
            # لو الحركة الحالية تشغيل، وآخر حدث مسجل في التايم لاين كان تشغيل برضه، الحمهما فوراً في سطر واحد!
            if is_active and timeline_events and timeline_events[-1]['is_active_event']:
                prev_event = timeline_events[-1]
                prev_event['end_dt'] = en_l
                prev_event['time_range'] = f"{prev_event['start_dt'].strftime('%H:%M')} - {en_l.strftime('%H:%M') if s.end_time else 'الآن'}"
                
                # تجمع الساعات الصافية للجلستين المتتاليتين في سطر العرض الملموم
                prev_event['total_dur'] += dur
                prev_event['duration_str'] = to_hhmm(prev_event['total_dur'])
            else:
                # لو الحركة توقف، أو أول حركة تشغيل في اليوم، افتح لها سطر جديد شيك ومستقل في الجدول
                timeline_events.append({
                    'start_dt': st_l, # متغير داخلي للحام العكسي
                    'end_dt': en_l,   # متغير داخلي للحام العكسي
                    'time_range': f"{st_l.strftime('%H:%M')} - {en_l.strftime('%H:%M') if s.end_time else 'الآن'}",
                    'description': s.get_status_display() + (f" : {s.stop_reason}" if s.stop_reason else ""),
                    'status': s.status,
                    'is_active_event': is_active, # علامة جودة ليعرف الكود أن السجل تشغيل وقابل للحام مع ما بعده
                    'total_dur': dur,
                    'duration_str': to_hhmm(dur)
                })


    performance_table = []
    for name, data in op_performance.items():
        rate = round(data['meters'] / data['work'], 2) if data['work'] > 0.1 else 0
        performance_table.append({
            'operator': name,
            'work_time_str': to_hhmm(data['work']),
            'stop_time_str': to_hhmm(data['stop']),
            'meters': data['meters'], 
            'rate': rate
        })

    first_s = shifts.first()
    last_s = shifts.last()
    day_start_fuel = first_s.fuel_start if first_s else 0.0
    day_end_fuel = last_s.fuel_end if (last_s and last_s.fuel_end > 0) else 0.0
    usage = (day_start_fuel + total_received) - day_end_fuel if day_end_fuel > 0 else 0.0
    last_with_coords = shifts.exclude(end_east__isnull=True).last() or last_s

    total_m3_calc = 0.0
    for s in shifts:
        m3_val = float(s.quantity_m3 or 0.0)
        if m3_val == 0.0 and s.depth_after and s.depth_before:
            m3_val = abs(float(s.depth_after or 0.0) - float(s.depth_before or 0.0)) * float(s.progress_meters or 0.0) * float(s.swing_width or 0.0)
        total_m3_calc += m3_val

    # 🪵 محرك الفرز الزمني لخطوط الطرد: يضمن سحب أرقام آخر وردية مسجلة أو معدلة في اليوم بالترتيب الزمني
    latest_floating = 0.0
    latest_land = 0.0
    
    # الـ shifts مرتبة من الصباح للمساء، فاللفة دي هتستقر تلقائياً عند آخر قراءة حقيقية بالدقيقة
    for s in shifts:        
        if s.floating_line is not None:
            latest_floating = float(s.floating_line)
        if s.land_line is not None:
            latest_land = float(s.land_line)

    context = {
        'report': report,
        'performance_table': performance_table,
        'timeline': timeline_events,
        'unique_operators': unique_operators,
        'total_m3': round(total_m3_calc, 2),
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
        
        # 💎 حقن القراءات الختامية الفعلية (زيادة أو تقصير) في كروت التقرير المجمع
        'floating_line': latest_floating,
        'land_line': latest_land,
        'total_line': latest_floating + latest_land,
    }
    return render(request, 'core/report_detail.html', context)

@login_required
def quick_action(request, dredger_id, action_type):
    from .models import DailyProjectReport, WorkShift, Staff, Dredger
    from django.shortcuts import render, redirect, get_object_or_404
    from django.utils import timezone
    from datetime import datetime
    import pytz

    dredger = get_object_or_404(Dredger, id=dredger_id)
    staff = Staff.objects.filter(user=request.user).first()
    if not staff:
        staff = Staff.objects.first() or Staff.objects.create(name="مدير النظام")

    cairo_tz = pytz.timezone('Africa/Cairo')
    now_l = timezone.now().astimezone(cairo_tz)

    prev = WorkShift.objects.filter(report_24h__dredger=dredger).order_by('-id').first()
    last_open = WorkShift.objects.filter(report_24h__dredger=dredger, end_time__isnull=True).last()

    def clean_num(val):
        if val is None or str(val).strip() == "": return 0.0
        try: return float(val)
        except: return 0.0

    inherited_fuel = prev.fuel_end if prev and clean_num(prev.fuel_end) > 0 else (prev.fuel_start if prev else 0.0)
    inherited_main = prev.main_engine_end if prev and clean_num(prev.main_engine_end) > 0 else (prev.main_engine_start if prev else 0.0)
    inherited_aux = prev.aux_engine_end if prev and clean_num(prev.aux_engine_end) > 0 else (prev.aux_engine_start if prev else 0.0)
    inherited_depth = prev.depth_after if prev and clean_num(prev.depth_after) > 0 else (prev.depth_before if prev else 0.0)
    
    inherited_east = prev.end_east if prev and prev.end_east else (prev.start_east if prev else "")
    inherited_north = prev.end_north if prev and prev.end_north else (prev.start_north if prev else "")
    inherited_floating = prev.floating_line if prev and prev.floating_line else ""
    inherited_land = prev.land_line if prev and prev.land_line else ""
    inherited_swing = prev.swing_width if prev and prev.swing_width else ""

    if request.method == "POST":
        user_date = request.POST.get('action_date')
        user_time = request.POST.get('action_time')
        
        try:
            full_str = f"{user_date} {user_time}"
            event_time = datetime.strptime(full_str, '%Y-%m-%d %H:%M').replace(tzinfo=None)
            event_time = cairo_tz.localize(event_time)
        except (ValueError, TypeError):
            event_time = now_l

        # 🗺️ محرك القص التاريخي المطور: لو ساعة الحركة الرقمية أقل من 12 ظهراً، ترحل فوراً لليوم السابق عافية
        report_date = event_time.date()
        
        # الفحص الرقمي الصافي للساعات (من 0 إلى 23) يمنع أي تضارب في الـ Timezone
        if event_time.hour < 12:
            report_date -= timedelta(days=1)

        # جلب أو إنشاء التقرير الممع لليوم الملحوم هندسياً
        report, _ = DailyProjectReport.objects.get_or_create(dredger=dredger, date_started=report_date)

        current_fuel = clean_num(request.POST.get('fuel_val')) or inherited_fuel
        current_main = clean_num(request.POST.get('main_engine_val')) or inherited_main
        current_aux = clean_num(request.POST.get('aux_engine_val')) or inherited_aux
        current_east = clean_num(request.POST.get('east_val')) or clean_num(inherited_east)
        current_north = clean_num(request.POST.get('north_val')) or clean_num(inherited_north)
        
        current_progress = clean_num(request.POST.get('progress_meters'))
        current_depth_before = clean_num(request.POST.get('depth_before')) or inherited_depth
        current_depth_after = clean_num(request.POST.get('depth_after')) or inherited_depth
        current_swing = clean_num(request.POST.get('swing_width')) or clean_num(inherited_swing)

        # ✂️ مقص الجلسات اللحظي لغلق الوردية القديمة وحقن عدادات النهاية بالملّي
        if last_open:
            last_open.end_time = event_time
            last_open.fuel_end = current_fuel
            last_open.main_engine_end = current_main
            last_open.aux_engine_end = current_aux
            last_open.end_east = current_east
            last_open.end_north = current_north
            last_open.progress_meters = current_progress
            last_open.depth_before = current_depth_before
            last_open.depth_after = current_depth_after
            last_open.swing_width = current_swing
            last_open.save() # حساب الساعات الصافية والمكعبات للقديمة فوراً بأمان

        # 🛡️ الحسم البرمجي العسكري: سحب الرمز الإنجليزي المعياري القادم من الـ HTML بالملّي ومنع العربي
        form_choice = request.POST.get('status_choice')
        
        if action_type == 'start':
            selected_status = 'active'
        elif action_type == 'handover':
            selected_status = 'handover'
        else:
            selected_status = form_choice if form_choice else 'other'

        # إنشاء الوردية الجديدة بالقيم الافتتاحية النظيفة
        new_shift = WorkShift(
            report_24h=report, operator=staff, status=selected_status, start_time=event_time,
            fuel_start=current_fuel, fuel_end=current_fuel, fuel_usage=0.0,
            main_engine_start=current_main, main_engine_end=current_main,
            aux_engine_start=current_aux, aux_engine_end=current_aux,
            depth_before=current_depth_after, depth_after=current_depth_after,
            swing_width=current_swing, progress_meters=0.0,
            floating_line=clean_num(request.POST.get('floating_line')) or clean_num(inherited_floating),
            land_line=clean_num(request.POST.get('land_line')) or clean_num(inherited_land),
            start_east=current_east, start_north=current_north, end_east=current_east, end_north=current_north,
            stop_reason=request.POST.get('notes') or ""
        )
        new_shift.save()
        return redirect('home')

    context = {
        'dredger': dredger, 'action_type': action_type,
        'current_date': now_l.strftime('%Y-%m-%d'), 'current_time': now_l.strftime('%H:%M'),
        'inherited': {
            'fuel': clean_num(inherited_fuel), 'main': clean_num(inherited_main), 'aux': clean_num(inherited_aux),
            'depth': clean_num(inherited_depth), 'east': inherited_east, 'north': inherited_north,
            'floating': inherited_floating, 'land': inherited_land, 'swing': inherited_swing
        }
    }
    return render(request, 'core/quick_action_form.html', context)

# --- دالة إغلاق التقارير القديمة تلقائياً ---
def auto_close_old_reports():
    cairo_tz = pytz.timezone('Africa/Cairo')
    now_local = timezone.now().astimezone(cairo_tz)
    today_noon = now_local.replace(hour=12, minute=0, second=0, microsecond=0)
    if now_local >= today_noon:
        DailyProjectReport.objects.filter(date_started__lt=now_local.date(), is_closed=False).update(is_closed=True)
    else:
        DailyProjectReport.objects.filter(date_started__lt=now_local.date() - timedelta(days=1), is_closed=False).update(is_closed=True)


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

    all_dredgers = Dredger.objects.all()

    dredger_id = request.GET.get('dredger_id')
    current_dredger = None
    if dredger_id:
        try:
            current_dredger = Dredger.objects.filter(id=int(dredger_id)).first()
        except (ValueError, TypeError):
            pass
    
    if not current_dredger:
        current_dredger = Dredger.objects.first()

    start_date_raw = request.GET.get('start_date')
    start_time_raw = request.GET.get('start_time', '12:00')
    end_date_raw = request.GET.get('end_date')
    end_time_raw = request.GET.get('end_time', '12:00')

    if start_date_raw and end_date_raw:
        try:
            start_full = f"{start_date_raw} {start_time_raw}"
            end_full = f"{end_date_raw} {end_time_raw}"
            start_date = datetime.strptime(start_full, '%Y-%m-%d %H:%M').replace(tzinfo=None)
            start_date = cairo_tz.localize(start_date)
            end_date = datetime.strptime(end_full, '%Y-%m-%d %H:%M').replace(tzinfo=None)
            end_date = cairo_tz.localize(end_date)
        except ValueError:
            start_date = (now_local - timedelta(days=30)).replace(hour=12, minute=0, second=0, microsecond=0)
            end_date = now_local.replace(hour=12, minute=0, second=0, microsecond=0)
    else:
        start_date = (now_local - timedelta(days=30)).replace(hour=12, minute=0, second=0, microsecond=0)
        end_date = now_local.replace(hour=12, minute=0, second=0, microsecond=0)

    if current_dredger:
        from django.db.models import Q
        target_shifts = WorkShift.objects.filter(
            report_24h__dredger=current_dredger
        ).filter(
            Q(start_time__range=(start_date, end_date)) | 
            Q(end_time__range=(start_date, end_date)) |
            Q(start_time__lte=start_date, end_time__gte=end_date)
        ).distinct()
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
        s_start = s.start_time.astimezone(cairo_tz)
        s_end = (s.end_time if s.end_time else timezone.now()).astimezone(cairo_tz)

        # ✂️ محرك مقص الحواف الرياضي المطور لمنع تداخل الساعات والالتزام بحدود الفلتر بالمللي
        actual_start = max(s_start, start_date)
        actual_end = min(s_end, end_date)

        if actual_start >= actual_end:
            continue

        dur = (actual_end - actual_start).total_seconds() / 3600

        m3_val = float(s.quantity_m3 or 0)
        if m3_val == 0 and s.depth_after > 0:
             m3_val = abs(s.depth_after - s.depth_before) * (s.progress_meters or 0) * (s.swing_width or 0)

        meters_val = float(s.progress_meters or 0)
        # ⛽ المعادلة الرياضية الفولاذية لصافي حرق السولار الفعلي للوردية لمنع تداخل التمويل
        f_start = float(s.fuel_start or 0.0)
        f_rec = float(s.fuel_received or 0.0)
        f_end = float(s.fuel_end or 0.0)
        
        # إذا سجل قفل الوردية، يحسب الحرق الفعلي، لو جارية (صفر) يحسب صفر لمنع الخصم
        if f_end > 0.0:
            fuel_val = max(0.0, (f_start + f_rec) - f_end)
        else:
            fuel_val = 0.0


        full_dur = (s_end - s_start).total_seconds() / 3600
        ratio = (dur / full_dur) if full_dur > 0 else 1

        m3_ratio = m3_val * ratio
        meters_ratio = meters_val * ratio
        fuel_ratio = fuel_val * ratio

        total_m3_period += m3_ratio
        total_meters_period += meters_ratio
        total_fuel_period += fuel_ratio

        name = s.operator.name if s.operator else "مشغل غير محدد"
        group = s.operator.group if s.operator else 'غير محدد'
        
        if name not in op_stats:
            op_stats[name] = {'m3': 0, 'meters': 0, 'work_h': 0, 'stops_h': 0, 'fuel': 0, 'group': group, 'count': 0}

        op_stats[name]['m3'] += m3_ratio
        op_stats[name]['meters'] += meters_ratio
        op_stats[name]['fuel'] += fuel_ratio
        op_stats[name]['count'] += 1

        if group in shift_battle:
            shift_battle[group]['m3'] += m3_ratio
            shift_battle[group]['meters'] += meters_ratio
            shift_battle[group]['fuel'] += fuel_ratio
            shift_battle[group]['shifts_count'] += 1

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

    # 🔥 الترتيب الهندسي الصحيح: نحسب ونحقن الـ meters_rate أولاً لكل كابتن قبل عملية الترتيب لمنع الـ KeyError
    for op in operators_ranking:
        op['meters_rate'] = round(op['meters'] / op['work_h'], 2) if op['work_h'] > 0.1 else 0

    # ⚖️ ميزان العدالة المطور: الفرز الآن بناءً على معدل الإنتاجية بالساعة (Rate) كخيار أول ومعدل الأمتار كخيار ثانٍ
    operators_ranking = sorted(operators_ranking, key=lambda x: (x['rate'], x['meters_rate']), reverse=True)

    final_battle = []
    for g_name, g_data in shift_battle.items():
        fuel_rate = round(g_data['fuel'] / g_data['m3'], 2) if g_data['m3'] > 0 else 0
        group_meters_rate = round(g_data['meters'] / g_data['work_h'], 2) if g_data['work_h'] > 0.1 else 0
        
        final_battle.append({
            'name': g_name, 
            'm3': round(g_data['m3'], 1), 
            'meters': round(g_data['meters'], 1),
            'work_h': round(g_data['work_h'], 1), 
            'stops': round(g_data['stops'], 1),
            'fuel': round(g_data['fuel'], 1), 
            'fuel_rate': fuel_rate, 
            'shifts_count': g_data['shifts_count'],
            'meters_rate': group_meters_rate
        })

    status_map = {
        'active': 'تشغيل فعلي (إنتاج)',
        'breakdown_mech': 'عطل ميكانيكي',
        'breakdown_elec': 'عطل كهربائي',
        'breakdown_hydrulic': 'عطل هيدروليك',
        'welding': 'أعمال لحام',
        'maintenance': 'صيانة دورية / عمرة',
        'anchors': 'نقل مخاطيف',
        'maneuver': 'تشفيت / تغيير موقع',
        'pipeline_washed': 'غسيل خط/ضخ مياه',
        'pipeline': 'فك / تركيب / إصلاح خط الطرد',
        'weather': 'توقف بسبب سوء الأحوال الجوية',
        'waiting_barge': 'انتظار صندل / تموين',
        'safety': 'توقف لأسباب تتعلق بالسلامة',
        'inspection': 'تفتيش / زيارة رسمية',
        'handover': 'استلام وتسليم وردية',
        'shift_end': 'نهاية وردية ( 12 ساعة)',
        'obstruction': 'عوائق بالتربة',
        'stone_box': 'فتح صندوق الحجارة',
        'cutter_check': 'التشييك على الكتر',
        'pipe_change': 'تغيير ماسورة بالخط',
        'rubber_change': 'تغيير رابر بالخط',
        'other': 'توقف لأسباب أخرى'
    }

    
    # 📊 محرك الفرز المزدوج المطور لتحليل الوقفات والأعطال (يمنع تصفير الشاشات والـ Charts)
    stop_analysis = []
    for g in ['A', 'B']:
        items = []
        for s_code, s_name in status_map.items():
            # 🔥 اللحام الفولاذي: البحث بالرمز الإنجليزي أو النص العربي لضمان قنص البيانات القديمة والجديدة معاً
            g_stops = target_shifts.filter(
                Q(operator__group=g) & 
                (Q(status=s_code) | Q(status=s_name))
            )
            
            if g_stops.exists():
                hrs = 0.0
                for ts in g_stops:
                    ts_start = ts.start_time.astimezone(cairo_tz)
                    ts_end = (ts.end_time if ts.end_time else timezone.now()).astimezone(cairo_tz)
                    act_s = max(ts_start, start_date)
                    act_e = min(ts_end, end_date)
                    if act_s < act_e:
                        hrs += (act_e - act_s).total_seconds() / 3600
                if hrs > 0.0:
                    items.append({'name': s_name, 'count': g_stops.count(), 'hours': round(hrs, 1)})
        stop_analysis.append({'group': g, 'items': items})

    context = {
        'total_m3': round(total_m3_period, 1), 'total_meters': round(total_meters_period, 1), 'total_fuel': round(total_fuel_period, 1),
        'month_start': start_date.strftime('%Y-%m-%d'), 'start_time': start_time_raw,
        'month_end': end_date.strftime('%Y-%m-%d'), 'end_time': end_time_raw,
        'operators_ranking': operators_ranking, 'stop_analysis': stop_analysis, 'final_battle': final_battle,
        'all_dredgers': all_dredgers,          
        'current_dredger': current_dredger,    
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

    report = get_object_or_404(PipeFighterOperations, id=report_id)

    all_items = InventoryItem.objects.filter(show_in_pipe=True).order_by('category', 'id')

    categorized_data = {}
    for item in all_items:
        item.quantity_found = item.quantity_pipe
        cat = item.category if item.category else "مهمات عامة"
        if cat == "الاستوك" or cat == "أخرى":
            continue

        if cat not in categorized_data:
            categorized_data[cat] = []
        categorized_data[cat].append(item)

    # 🔒 التلقيم الهندسي المطابق للـ HTML: تغيير المفتاح الداخلي ليكون quantity_pipe بالمللي
    stock_data = {
        'pipes_new': {'quantity_pipe': report.stock_pipes_new},
        'pipes_used': {'quantity_pipe': report.stock_pipes_used},
        'pipes_scrap': {'quantity_pipe': report.stock_pipes_scrap},

        'rubbers_new': {'quantity_pipe': report.stock_rubbers_new},
        'rubbers_used': {'quantity_pipe': report.stock_rubbers_used},
        'rubbers_scrap': {'quantity_pipe': report.stock_rubbers_scrap},

        'pontoons_new': {'quantity_pipe': report.stock_pontoons_new},
        'pontoons_used': {'quantity_pipe': report.stock_pontoons_used},
        'pontoons_scrap': {'quantity_pipe': report.stock_pontoons_scrap},
    }

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
def pipefighter_form_view(request):
    from .models import PipeFighterOperations, Staff, InventoryItem
    from django.utils import timezone
    from django.contrib import messages
    from django.shortcuts import render, redirect

    staff = Staff.objects.filter(user=request.user).first() or Staff.objects.first()
    if not staff:
        from django.contrib.auth.models import User
        admin_user = User.objects.filter(is_superuser=True).first()
        staff = Staff.objects.create(user=admin_user, name="مدير النظام")

    last = PipeFighterOperations.objects.order_by('-id').first()

    raw_items = InventoryItem.objects.filter(show_in_pipe=True).order_by('id')
    if not raw_items.exists():
        raw_items = InventoryItem.objects.all()[:10]

    pipe_items_final = []
    seen_names = set()
    for item in raw_items:
        clean_name = item.name.strip().lower()
        if clean_name not in seen_names:
            item.current_qty = item.quantity_pipe
            pipe_items_final.append(item)
            seen_names.add(clean_name)

    if request.method == "POST":
        # محرك الوراثة الذكي: لو نسي يكتب أي خانة، يسحب القيمة السابقة فوراً لتأمين الوردية
        def to_int_or_inherit(val, field_name):
            if val is not None and val.strip() != "":
                try: return int(val)
                except: return 0
            if last:
                return getattr(last, field_name, 0)
            return 0

        report = PipeFighterOperations.objects.create(
            operator_in_charge=staff,
            shift=request.POST.get('shift', 'morning'),

            float_pipes=to_int_or_inherit(request.POST.get('float_pipes'), 'float_pipes'),
            float_rubbers=to_int_or_inherit(request.POST.get('float_rubbers'), 'float_rubbers'),
            float_pontoons=to_int_or_inherit(request.POST.get('float_pontoons'), 'float_pontoons'),
            float_pantons=to_int_or_inherit(request.POST.get('float_pantons'), 'float_pantons'),
            float_anchors=to_int_or_inherit(request.POST.get('float_anchors'), 'float_anchors'),
            land_pipes=to_int_or_inherit(request.POST.get('land_pipes'), 'land_pipes'),
            land_rubbers=to_int_or_inherit(request.POST.get('land_rubbers'), 'land_rubbers'),

            stock_pipes_new=to_int_or_inherit(request.POST.get('stock_pipes_new'), 'stock_pipes_new'),
            stock_pipes_used=to_int_or_inherit(request.POST.get('stock_pipes_used'), 'stock_pipes_used'),
            stock_pipes_scrap=to_int_or_inherit(request.POST.get('stock_pipes_scrap'), 'stock_pipes_scrap'),
            stock_rubbers_new=to_int_or_inherit(request.POST.get('stock_rubbers_new'), 'stock_rubbers_new'),
            stock_rubbers_used=to_int_or_inherit(request.POST.get('stock_rubbers_used'), 'stock_rubbers_used'),
            stock_rubbers_scrap=to_int_or_inherit(request.POST.get('stock_rubbers_scrap'), 'stock_rubbers_scrap'),
            stock_pontoons_new=to_int_or_inherit(request.POST.get('stock_pontoons_new'), 'stock_pontoons_new'),
            stock_pontoons_used=to_int_or_inherit(request.POST.get('stock_pontoons_used'), 'stock_pontoons_used'),
            stock_pontoons_scrap=to_int_or_inherit(request.POST.get('stock_pontoons_scrap'), 'stock_pontoons_scrap'),

            bolts_30=to_int_or_inherit(request.POST.get('bolts_30'), 'bolts_30'),
            bolts_27=to_int_or_inherit(request.POST.get('bolts_27'), 'bolts_27'),
            bolts_24=to_int_or_inherit(request.POST.get('bolts_24'), 'bolts_24'),

            wrench_30=to_int_or_inherit(request.POST.get('wrench_30'), 'wrench_30'),
            wrench_27=to_int_or_inherit(request.POST.get('wrench_27'), 'wrench_27'),
            wrench_24=to_int_or_inherit(request.POST.get('wrench_24'), 'wrench_24'),

            socket_30=to_int_or_inherit(request.POST.get('socket_30'), 'socket_30'),
            socket_27=to_int_or_inherit(request.POST.get('socket_27'), 'socket_27'),
            socket_24=to_int_or_inherit(request.POST.get('socket_24'), 'socket_24'),

            air_gun=to_int_or_inherit(request.POST.get('air_gun'), 'air_gun'),
            work_description=request.POST.get('work_description', '')
        )

        for item in pipe_items_final:
            qty_raw = request.POST.get(f'qty_{item.id}')
            if qty_raw is not None and qty_raw.strip() != "":
                try:
                    InventoryItem.objects.filter(id=item.id).update(quantity_pipe=float(qty_raw))
                except Exception: continue

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
                    InventoryItem.objects.create(
                        name=clean_n,
                        category=cat_name,
                        show_in_pipe=True,
                        quantity_pipe=qty_val,
                        quantity=qty_val
                    )

        report.save()
        messages.success(request, "تم حفظ تقرير الخط بنجاح.")
        return redirect('pipe_report_detail', report_id=report.id)

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
        # استدعاء موضعي سريع لحل المشكلة فوراً دون تداخل
    from .models import MarineInventoryReport

    # جلب تقارير الكراكة فقط
    reports = MarineInventoryReport.objects.filter(report_type='marine').order_by('-date')
    return render(request, 'core/marine_inventory_list.html', {'reports': reports})

