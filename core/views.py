import requests, pytz
from django.contrib import messages
from django.shortcuts import render, redirect, get_object_or_404
from django.db.models import Sum, Max, Min, F, Q
from django.utils import timezone
from datetime import timedelta, datetime, time
from .models import NewsTicker, WorkShift, Dredger, PipeFighterOperations, Staff, DailyProjectReport, WeeklyRotation

# --- 1. وظيفة الإغلاق التلقائي لليوم ---
def auto_close_old_reports():
    now = timezone.now()
    cairo_tz = pytz.timezone('Africa/Cairo')
    now_local = now.astimezone(cairo_tz)
    today_noon = now_local.replace(hour=12, minute=0, second=0, microsecond=0)
    
    if now_local >= today_noon:
        DailyProjectReport.objects.filter(date_started__lt=now_local.date(), is_closed=False).update(is_closed=True)
    else:
        DailyProjectReport.objects.filter(date_started__lt=now_local.date() - timedelta(days=1), is_closed=False).update(is_closed=True)

# --- 2. الصفحة الرئيسية ---
def home(request):
    auto_close_old_reports()
    dredgers = Dredger.objects.all()
    dredger_status_list = []
    
    cairo_tz = pytz.timezone('Africa/Cairo')
    now_local = timezone.now().astimezone(cairo_tz)
    today_date = now_local.date()
    
    current_rotation = WeeklyRotation.objects.order_by('-start_date').first()
    active_group = current_rotation.active_group if current_rotation else None
    staff_member = Staff.objects.filter(user=request.user).first()
    news = NewsTicker.objects.filter(is_active=True).order_by('-created_at')

    for d in dredgers:
        last_shift = WorkShift.objects.filter(report_24h__dredger=d).order_by('-id').first()
        status_text = last_shift.get_status_display() if last_shift else "غير محدد"
        status_code = last_shift.status if last_shift else 'inactive'
        op_name = last_shift.operator.name if last_shift and last_shift.operator else "لا يوجد"
        op_phone = last_shift.operator.phone if last_shift and last_shift.operator and last_shift.operator.phone else "N/A"

        is_handed_over = True
        current_active_operator = None
        if last_shift and not last_shift.end_time:
            is_handed_over = False
            current_active_operator = last_shift.operator

        is_owner = (staff_member == current_active_operator)
        can_view = (request.user.is_superuser or (staff_member and staff_member.team_type == 'dredger') or (request.user in d.allowed_operators.all()))
        
        can_add = False
        if request.user.is_superuser: can_add = True
        elif staff_member and can_view and staff_member.group == active_group:
            if is_handed_over or is_owner: can_add = True

                # داخل حلقة for d in dredgers في دالة home
        dredger_status_list.append({
            'object': d,           # هام جداً للروابط
            'id': d.id,            # كخطة بديلة
            'name': d.name,
            'can_view': can_view,
            'can_add': can_add,
            'is_handed_over': is_handed_over,
            'is_owner': is_owner,
            'status_code': status_code,
            'status_text': status_text,
            'op_name': op_name,
            'op_phone': op_phone,
            'vessel_phone': d.vessel_phone,
            # بيانات السولار السريعة للعرض (لو احتجتها في الـ index)
            'fuel_info': {
                'stock': round(d.stock_fuel - (WorkShift.objects.filter(report_24h__dredger=d).aggregate(Sum('fuel_added'))['fuel_added__sum'] or 0), 2),
                'net': round((WorkShift.objects.filter(report_24h__dredger=d).aggregate(Sum('fuel_added'))['fuel_added__sum'] or 0) - (WorkShift.objects.filter(report_24h__dredger=d).aggregate(Sum('fuel_usage'))['fuel_usage__sum'] or 0), 2),
            }
        })


    production_data, labels = [], []
    for i in range(6, -1, -1):
        target_date = today_date - timedelta(days=i)
        day_sum = WorkShift.objects.filter(report_24h__date_started=target_date).aggregate(Sum('quantity_m3'))['quantity_m3__sum'] or 0
        production_data.append(day_sum)
        labels.append(target_date.strftime('%d %b'))

    return render(request, 'core/index.html', {
        'news': news, 'dredger_status_list': dredger_status_list,
        'labels': labels, 'production_data': production_data
    })

def quick_action(request, dredger_id, action_type):
    if not request.user.is_authenticated: return redirect('/admin/login/')
    
    dredger = get_object_or_404(Dredger, id=dredger_id)
    staff = Staff.objects.filter(user=request.user).first()
    cairo_tz = pytz.timezone('Africa/Cairo')
    now = timezone.now()
    now_local = now.astimezone(cairo_tz)
    
    report_date = now_local.date()
    if now_local.time() < time(12, 0): report_date -= timedelta(days=1)
    
    # جلب أحدث سجل للكراكة لتوريث القراءات
    prev = WorkShift.objects.filter(report_24h__dredger=dredger).order_by('-id').first()
    last_open = WorkShift.objects.filter(report_24h__dredger=dredger, end_time__isnull=True).last()

    # منطق فصل الوردية عند الساعة 12 ظهراً (كما برمجناه سابقاً)
    if last_open:
        start_local = last_open.start_time.astimezone(cairo_tz)
        limit_noon = now_local.replace(hour=12, minute=0, second=0, microsecond=0)
        if start_local < limit_noon <= now_local:
            last_open.end_time = limit_noon
            # عند القفل التلقائي نعتبر قراءة النهاية هي نفس البداية مؤقتاً لحين تعديل المشغل
            last_open.fuel_end = last_open.fuel_start + last_open.fuel_received
            last_open.main_engine_end = last_open.main_engine_start
            last_open.save()
            
            messages.warning(request, "Shift split at 12:00 PM. Please update morning production/fuel.")
            report_today, _ = DailyProjectReport.objects.get_or_create(dredger=dredger, date_started=report_date)
            last_open = WorkShift.objects.create(
                report_24h=report_today, operator=last_open.operator, status=last_open.status,
                start_time=limit_noon, fuel_start=last_open.fuel_end,
                main_engine_start=last_open.main_engine_end, aux_engine_start=last_open.aux_engine_end
            )

    report, _ = DailyProjectReport.objects.get_or_create(dredger=dredger, date_started=report_date)

    if action_type == 'start':
        if last_open:
            last_open.end_time = now
            last_open.save()
        
        # إنشاء سجل "تشغيل" جديد مع سحب قراءات العدادات من آخر سجل مغلق
        new_s = WorkShift.objects.create(
            report_24h=report, operator=staff, status='active', start_time=now,
            # توريث السولار والمحركات (بداية الجديد = نهاية القديم)
            fuel_start=prev.fuel_end if prev else 0,
            main_engine_start=prev.main_engine_end if prev else 0,
            aux_engine_start=prev.aux_engine_end if prev else 0,
            # توريث الموقع والخط
            start_east=prev.end_east if prev else None,
            start_north=prev.end_north if prev else None,
            floating_line=prev.floating_line if prev else 0,
            land_line=prev.land_line if prev else 0
        )
        return redirect(f'/admin/core/workshift/{new_s.id}/change/?dredger_id={dredger_id}')

    elif action_type == 'stop':
        target_shift = last_open if (last_open and last_open.operator == staff) else None
        
        if target_shift:
            target_shift.status = 'breakdown'
            target_shift.end_time = now
            # إجبار القيم على الظهور: نهاية = بداية (عشان المشغل يزود بس)
            target_shift.fuel_end = target_shift.fuel_start + target_shift.fuel_received
            target_shift.main_engine_end = target_shift.main_engine_start
            target_shift.aux_engine_end = target_shift.aux_engine_start
            
            target_shift.save()
            return redirect(f'/admin/core/workshift/{target_shift.id}/change/')
        else:
            # لو مفيش وردية مفتوحة (طوارئ)
            new_s = WorkShift.objects.create(
                report_24h=report, operator=staff, status='breakdown',
                start_time=now, end_time=now,
                fuel_start=prev.fuel_end if prev else 0,
                main_engine_start=prev.main_engine_end if prev else 0,
                aux_engine_start=prev.aux_engine_end if prev else 0
            )
            new_s.fuel_end = new_s.fuel_start
            new_s.main_engine_end = new_s.main_engine_start
            new_s.aux_engine_end = new_s.aux_engine_start
            new_s.save()
            return redirect(f'/admin/core/workshift/{new_s.id}/change/')

    elif action_type == 'handover':
        if last_open and last_open.operator == staff:
            last_open.end_time = now
            last_open.save()
            return redirect(f'/admin/core/workshift/{last_open.id}/change/?dredger_id={dredger_id}')
            
    return redirect('home')

# --- 4. أرشيف التقارير (الدوال التي كانت مفقودة) ---
def reports_list(request):
    reports = DailyProjectReport.objects.all().order_by('-date_started')
    return render(request, 'core/reports_list.html', {'reports': reports})

def report_detail(request, report_id):
    report = get_object_or_404(DailyProjectReport, id=report_id)
    # جلب كافة الورديات مرتبة زمنياً لليوم بالكامل
    shifts = report.shifts.all().order_by('start_time')
    cairo_tz = pytz.timezone('Africa/Cairo')
    now = timezone.now()
    
    def to_hhmm(decimal_hours):
        if not decimal_hours or decimal_hours < 0: return "00:00"
        total_mins = int(round(decimal_hours * 60))
        hrs, mins = divmod(total_mins, 60)
        return f"{hrs:02d}:{mins:02d}"

    unique_operators, timeline_events, stop_summary_dict, shifts_data = [], [], {}, []
    total_work_dec, total_stop_dec = 0, 0
    
    # متغيرات التجميع لليوم
    day_fuel_usage = 0
    day_main_engine_h = 0
    day_aux_engine_h = 0

    if shifts.exists():
        current_ev = None
        for s in shifts:
            # 1. جمع الأسماء الفريدة
            if s.operator and s.operator.name not in unique_operators: 
                unique_operators.append(s.operator.name)
            
            # 2. تحديد نهاية الفترة للحساب اللحظي
            eff_end = s.end_time if s.end_time else now
            duration = (eff_end - s.start_time).total_seconds() / 3600 if s.start_time else 0
            
            # 3. تصنيف الحالة وجمع الساعات والاستهلاك
            is_active = (s.status == 'active')
            if is_active:
                total_work_dec += duration
            else:
                total_stop_dec += duration
                lbl = s.get_status_display()
                stop_summary_dict[lbl] = stop_summary_dict.get(lbl, 0) + duration
            
            # تجميع بيانات المحركات والسولار المحسوبة في الموديل
            day_fuel_usage += (s.fuel_usage or 0)
            day_main_engine_h += (s.main_engine_hours or 0)
            day_aux_engine_h += (s.aux_engine_hours or 0)

            # 4. تجهيز بيانات الجدول السفلي
            shifts_data.append({
                'obj': s, 
                'work_h': to_hhmm(duration) if is_active else "00:00", 
                'stop_h': to_hhmm(duration) if not is_active else "00:00"
            })
            
            # 5. منطق دمج التايم لاين
            if current_ev is None:
                current_ev = {'status': s.status, 'start': s.start_time, 'end': eff_end, 'reason': s.stop_reason or "", 'is_open': not s.end_time}
            else:
                if s.status == current_ev['status']:
                    current_ev['end'] = eff_end
                    current_ev['is_open'] = not s.end_time
                    if s.stop_reason and s.stop_reason not in current_ev['reason']: 
                        current_ev['reason'] += f" | {s.stop_reason}"
                else:
                    timeline_events.append(current_ev)
                    current_ev = {'status': s.status, 'start': s.start_time, 'end': eff_end, 'reason': s.stop_reason or "", 'is_open': not s.end_time}
        
        if current_ev: 
            timeline_events.append(current_ev)

    # 6. تجهيز التايم لاين النهائي للعرض
    final_timeline = []
    for ev in timeline_events:
        st_l = ev['start'].astimezone(cairo_tz)
        en_l = ev['end'].astimezone(cairo_tz)
        d_h = (ev['end'] - ev['start']).total_seconds() / 3600
        disp = dict(WorkShift.STATUS_CHOICES).get(ev['status'], ev['status'])
        
        final_timeline.append({
            'time_range': f"{st_l.strftime('%H:%M')} - {en_l.strftime('%H:%M') if not ev['is_open'] else 'الآن'}",
            'description': "في الخدمة (تكريك فعلي)" if ev['status'] == 'active' else f"{disp} : {ev['reason']}" if ev['reason'] else disp,
            'status': ev['status'],
            'duration_str': to_hhmm(d_h)
        })

    # 7. حساب بيانات كروت المحركات (البداية والنهاية والصافي)
    first_s = shifts.first()
    last_s = shifts.last()
    
    main_engine_data = {
        'start': first_s.main_engine_start if first_s else 0,
        'end': last_s.main_engine_end if (last_s and last_s.main_engine_end > 0) else (last_s.main_engine_start if last_s else 0),
        'net': to_hhmm(day_main_engine_h)
    }

    aux_engine_data = {
        'start': first_s.aux_engine_start if first_s else 0,
        'end': last_s.aux_engine_end if (last_s and last_s.aux_engine_end > 0) else (last_s.aux_engine_start if last_s else 0),
        'net': to_hhmm(day_aux_engine_h)
    }

    # 8. إحداثيات بداية ونهاية اليوم
    start_coords = {
        'east': first_s.start_east if first_s else "0.0",
        'north': first_s.start_north if first_s else "0.0"
    }
    last_with_coords = shifts.exclude(end_east__isnull=True).last() or shifts.last()
    end_coords = {
        'east': last_with_coords.end_east if last_with_coords and last_with_coords.end_east else (last_with_coords.start_east if last_with_coords else "0.0"),
        'north': last_with_coords.end_north if last_with_coords and last_with_coords.end_north else (last_with_coords.start_north if last_with_coords else "0.0")
    }

    context = {
        'report': report,
        'shifts_data': shifts_data,
        'timeline': final_timeline,
        'stop_summary': [{'reason': k, 'duration': to_hhmm(v)} for k, v in stop_summary_dict.items()],
        'unique_operators': unique_operators,
        'total_m3': round(sum(s.quantity_m3 for s in shifts), 2),
        'total_meters': round(sum(s.progress_meters for s in shifts), 2),
        'total_work_hours': to_hhmm(total_work_dec),
        'total_stop_hours': to_hhmm(total_stop_dec),
        'total_fuel_usage': round(day_fuel_usage, 2),
        'main_engine': main_engine_data,
        'aux_engine': aux_engine_data,
        'start_coords': start_coords,
        'end_coords': end_coords,
        'floating_line': shifts.last().floating_line if shifts.exists() else 0,
        'land_line': shifts.last().land_line if shifts.exists() else 0,
        'total_line': (shifts.last().floating_line or 0) + (shifts.last().land_line or 0) if shifts.exists() else 0,
    }
    return render(request, 'core/report_detail.html', context)

# --- 5. التحليلات ---
def analytics_view(request):
    dredgers = Dredger.objects.all()
    dredger_analytics = []
    def to_hhmm(decimal_hours):
        if not decimal_hours or decimal_hours < 0: return "00:00"
        total_mins = int(round(decimal_hours * 60))
        hrs, mins = divmod(total_mins, 60)
        return f"{hrs:02d}:{mins:02d}"

    for d in dredgers:
        shifts = WorkShift.objects.filter(report_24h__dredger=d)
        
        # 1. إجمالي المستهلك (منذ بداية المشروع)
        total_consumed = shifts.aggregate(Sum('fuel_usage'))['fuel_usage__sum'] or 0
        
        # 2. إجمالي المضاف للكراكة (التموين)
        total_added = shifts.aggregate(Sum('fuel_added'))['fuel_added__sum'] or 0
        
        # 3. الصافي الموجود في الكراكة (المضاف - المستهلك)
        current_in_vessel = total_added - total_consumed
        
        # 4. الكمية في الاستوك (الموجود في المخزن - المضاف للكراكات)
        # ملاحظة: يتم تحديث stock_fuel يدوياً من الأدمين عند شراء سولار جديد
        current_stock = d.stock_fuel - total_added
        shifts = WorkShift.objects.filter(report_24h__dredger=d)
        stats = shifts.aggregate(total_m3=Sum('quantity_m3'), total_fuel=Sum('fuel_usage'), total_meters=Sum('progress_meters'), max_e=Max('main_engine_hours'), min_e=Min('main_engine_hours'))
        dredger_analytics.append({
            'dredger': d, 'total_m3': stats['total_m3'] or 0, 'total_fuel': stats['total_fuel'] or 0,
            'total_meters': stats['total_meters'] or 0, 'engine_hours_str': to_hhmm((stats['max_e'] or 0)-(stats['min_e'] or 0)),
            'downtime_count': shifts.exclude(status='active').count(),
            'fuel_info': {
                'stock': round(current_stock, 2),
                'vessel': round(current_in_vessel, 2),
                'consumed': round(total_consumed, 2),
                'net': round(current_in_vessel, 2) # الصافي هو المتاح للعمل حالياً
            }
        })
    overall_stats = {
        'total_project_m3': sum(item['total_m3'] for item in dredger_analytics),
        'total_project_meters': sum(item['total_meters'] for item in dredger_analytics),
        'total_downtime_events': sum(item['downtime_count'] for item in dredger_analytics),
    }
    dredger_analytics_json = [{'name': item['dredger'].name, 'm3': float(item['total_m3']), 'fuel': float(item['total_fuel'])} for item in dredger_analytics]
    return render(request, 'core/analytics.html', {'dredger_analytics': dredger_analytics, 'overall_stats': overall_stats, 'dredger_analytics_json': dredger_analytics_json})

def fuel_report(request, dredger_id):
    dredger = get_object_or_404(Dredger, id=dredger_id)
    # جلب كافة السجلات التي تحتوي على تزويد أو استهلاك
        # حذفنا كلمة models. قبل الـ Q
    fuel_records = WorkShift.objects.filter(
        report_24h__dredger=dredger
    ).filter(Q(fuel_added__gt=0) | Q(fuel_usage__gt=0)).order_by('-start_time')


    # الحسابات الإجمالية
    total_added = sum(r.fuel_added for r in fuel_records)
    total_consumed = sum(r.fuel_usage for r in fuel_records)
    in_vessel = total_added - total_consumed
    stock_remaining = dredger.stock_fuel - total_added

    context = {
        'dredger': dredger,
        'records': fuel_records,
        'total_added': total_added,
        'total_consumed': total_consumed,
        'in_vessel': in_vessel,
        'stock_remaining': stock_remaining,
    }
    return render(request, 'core/fuel_report.html', context)
