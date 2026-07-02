import pytz
from datetime import time, timedelta, datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.utils import timezone
from django.utils.timezone import localtime
from django.db.models import Sum, Q
from .models import DailyProjectReport, ProcurementOrder, WorkShift, Staff, Dredger, WeeklyRotation, NewsTicker, PipeFighterOperations, InventoryItem


@login_required(login_url='/accounts/login/')
def home(request):
    from .models import EmergencyAlert, Dredger, WorkShift, WeeklyRotation, NewsTicker, Staff
    import pytz
    from django.utils import timezone

    if 'auto_close_old_reports' in globals():
        auto_close_old_reports()
        
    # 🛡️ محرك الفرز الأمني الفابريكا القاطع: حجب الكراكات عن المشغلين عافية من جذر الدالة
    if request.user.is_staff or request.user.is_superuser:
        # 👑 الإدارة العليا: فتح الأسطول بالكامل للمطالعة والتحليل
        dredgers = Dredger.objects.all()
    else:
        # ⚓ المشغلين والكباتن: قنص كراكة المشغل الحالي الملقمة في حسابه بالملّي
        current_staff = Staff.objects.filter(user=request.user).first()
        
        # الفحص: لو المشغل مربوط بكراكة معينة في قاعدة البيانات
        if current_staff and current_staff.dredger:
            dredgers = Dredger.objects.filter(id=current_staff.dredger.id)
        else:
            # حماية تراجعية لو مش مربوط بحاجة ميرجعش بيانات فارغة تضرب إيرور
            dredgers = Dredger.objects.none()

    # 🟢 تم تنظيف السطور هنا لمنع تكرار جلب dredgers عشوائياً بالأسفل
    dredger_status_list = []
    cairo_tz = pytz.timezone('Africa/Cairo')
    now_local = timezone.now().astimezone(cairo_tz)
    today_date = now_local.date()
    
    current_rotation = WeeklyRotation.objects.order_by('-start_date').first()
    active_group = current_rotation.active_group if current_rotation else None
    staff_member = Staff.objects.filter(user=request.user).first() if request.user.is_authenticated else None
    news = NewsTicker.objects.filter(is_active=True).order_by('-created_at')

    # 🚀 هندسة السرعة القصوى 1: شحن الورديات الأخيرة والعهد وبلاغات الطوارئ لايف
    for d in dredgers:
        all_dredger_shifts = WorkShift.objects.filter(report_24h__dredger=d).select_related('operator').order_by('-id')
        last_shift = all_dredger_shifts.first()
        prev_shift = all_dredger_shifts[1] if all_dredger_shifts.count() > 1 else None
        
        status_text = last_shift.get_status_display() if last_shift else "غير محدد"
        status_code = last_shift.status if last_shift else 'inactive'
        op_name = last_shift.operator.name if last_shift and last_shift.operator else "لا يوجد"
        op_phone = last_shift.operator.phone if last_shift and last_shift.operator and last_shift.operator.phone else "N/A"
        
        # 🛡️ الفحص الفوري القاطع للعهدة
        is_handed_over = False
        if last_shift:
            if last_shift.status in ['handover', 'shift_end'] or last_shift.stop_reason == "عهدة معلقة بانتظار الاستلام":
                is_handed_over = True

        current_active_operator = last_shift.operator if last_shift else None
        is_owner = (staff_member == current_active_operator) if staff_member and current_active_operator else False
        
        if is_handed_over:
            is_owner = False

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

        # 🚨 قنص البلاغ النشط الحالي للكراكة الحالية ديناميكياً
        active_alert = EmergencyAlert.objects.filter(dredger=d, is_resolved=False).order_by('-id').first()
        active_alert_text = active_alert.get_alert_type_display() if active_alert else None
        active_alert_user = active_alert.operator.name if active_alert and active_alert.operator else "غير محدد"
        active_alert_time = active_alert.created_at.astimezone(cairo_tz).strftime('%H:%M') if active_alert else None
        active_alert_id = active_alert.id if active_alert else None
        # 🟢 قفل حلقة الـ for وحقن البيانات الصافية في القاموس المعتمد للـ HTML لربط الطوارئ والشريط الأحمر
        dredger_status_list.append({
            'object': d, 'id': d.id, 'name': d.name, 'can_view': can_view, 'can_add': can_add,
            'is_handed_over': is_handed_over, 'is_owner': is_owner, 
            'status_code': status_code,
            'status_text': status_text, 'op_name': op_name, 'op_phone': op_phone, 'vessel_phone': d.vessel_phone,
            'current_fuel': round(current_fuel_val, 0), 'fuel_alert': 'success' if current_fuel_val >= 10000 else 'danger',
            
            'has_alert': True if active_alert else False,
            'alert_text': active_alert_text,
            'alert_user': active_alert_user,
            'alert_time': active_alert_time,
            'alert_id': active_alert_id,
        })

    # 🚀 هندسة السرعة القصوى 2: استعلام واحد خاطف وموحد لإنتاجية الـ 7 أيام الأخيرة
    seven_days_ago = today_date - timedelta(days=6)
    from django.db.models import Sum
    
    # جلب المجاميع دفعة واحدة مجمعة بالتاريخ بناءً على الكراكات المفلترة أمنياً فوق
    db_sums = WorkShift.objects.filter(
        report_24h__dredger__in=dredgers, # تقييد حسابات الرسم البياني أيضاً بكراكة المشغل فقط للأمان الكامل
        report_24h__date_started__range=(seven_days_ago, today_date)
    ).values('report_24h__date_started').annotate(total_day_m3=Sum('quantity_m3'))
    
    # تحويل الناتج لقاموس سريع للقنص اللحظي بالذاكرة
    sums_dict = {item['report_24h__date_started']: item['total_day_m3'] for item in db_sums if item['report_24h__date_started']}

    labels, production_data = [], []
    for i in range(6, -1, -1):
        target_date = today_date - timedelta(days=i)
        labels.append(target_date.strftime('%d %b'))
        # سحب المجموع من الذاكرة (سرعة طيارة وصفر ضغط على الـ CPU)
        production_data.append(sums_dict.get(target_date, 0.0))

    return render(request, 'core/index.html', {
        'news': news, 
        'dredger_status_list': dredger_status_list, 
        'labels': labels, 
        'production_data': production_data
    })

@login_required
def report_detail(request, report_id):
    # 🚀 هندسة السرعة الفائقة المفتوحة: جلب التقرير الرئيسي المطلوب
    report = get_object_or_404(DailyProjectReport.objects.select_related('dredger'), id=report_id)
    
    # جلب كل الورديات المربوطة بالتقرير مرتبة تصاعدياً من 12 ظهراً لـ 12 ظهراً
    shifts = report.shifts.all().select_related('operator__user').order_by('start_time')
    cairo_tz = pytz.timezone('Africa/Cairo')
    now = timezone.now()

    def to_hhmm(decimal_hours):
        if not decimal_hours or decimal_hours < 0: return "00:00"
        total_mins = int(round(decimal_hours * 60))
        hrs, mins = divmod(total_mins, 60)
        return f"{hrs:02d}:{mins:02d}"

    # تثبيت وإعلان متغيرات التجميع الكبرى الموحدة للمشروع لمنع تداخل الـ CPU
    op_performance = {}
    timeline_events = []
    unique_operators = [] 
    
    total_work_dec = 0.0
    total_stop_dec = 0.0
    total_meters_calc = 0.0
    total_m3_calc = 0.0
    total_received = 0.0

    # 💎 1. محرك قنص البداية المطلقة: من أول سجل مسجل في اليوم الهندسي تماماً (الساعة 12 ظهراً)
    first_absolute_shift = shifts.first()
    day_start_fuel = first_absolute_shift.fuel_start if first_absolute_shift else 0.0
    m_start_abs = float(first_absolute_shift.main_engine_start or 0.0) if first_absolute_shift else 0.0
    a_start_abs = float(first_absolute_shift.aux_engine_start or 0.0) if first_absolute_shift else 0.0
    
    start_east_val = first_absolute_shift.start_east if (first_absolute_shift and first_absolute_shift.start_east) else "0.0"
    start_north_val = first_absolute_shift.start_north if (first_absolute_shift and first_absolute_shift.start_north) else "0.0"

    # 💎 2. محرك القنص المطلق للنهاية: يقش قراءات القفل من آخر سجل مسجل مطلقاً في خريطة اليوم (سواء مقفول أو مفتوح)
    # 💎 2. محرك القنص والـ Live المطلق للنهاية الشامل: 
    # قش كافة قراءات القفل والـ 9000 لتر والعدادات والأعماق والخطوط مباشرة من آخِر سجل مسجل للكراكة في قاعدة البيانات بالكامل لايف
    # 💎 2. محرك القنص والـ Live المطلق المأمن:
    # قش كافة قراءات القفل والعدادات مباشرة من آخِر سجل مسجل للكراكة "جوه تقرير النهارده أو قبله" عافية ومنع هروبها لبكره
    last_absolute_shift = report.shifts.model.objects.filter(
        report_24h__dredger=report.dredger,
        report_24h__date_started__lte=report.date_started
    ).order_by('-id').first()
    
    if not last_absolute_shift:
        last_absolute_shift = shifts.last()

    # 🟢 أ. سحب عدادات السولار والماكينات لايف الحين
    day_end_fuel = last_absolute_shift.fuel_end if (last_absolute_shift and last_absolute_shift.fuel_end > 0.0) else day_start_fuel
    m_end_abs = float(last_absolute_shift.main_engine_end or 0.0) if last_absolute_shift else m_start_abs
    a_end_abs = float(last_absolute_shift.aux_engine_end or 0.0) if last_absolute_shift else a_start_abs
    
    # 🟢 ب. سحب الإحداثيات الجغرافية للقفل لايف
    end_east_val = last_absolute_shift.end_east if (last_absolute_shift and last_absolute_shift.end_east and last_absolute_shift.end_east != "0.0") else start_east_val
    end_north_val = last_absolute_shift.end_north if (last_absolute_shift and last_absolute_shift.end_north and last_absolute_shift.end_north != "0.0") else start_north_val

    # 🟢 ج. سحب خطوط الطرد البرية والعائمة وعرض التأرجح وأعماق النهاية الفعليّة لايف من آخر سجل
    latest_floating = float(last_absolute_shift.floating_line or 0.0) if last_absolute_shift and last_absolute_shift.floating_line else 0.0
    latest_land = float(last_absolute_shift.land_line or 0.0) if last_absolute_shift and last_absolute_shift.land_line else 0.0
    latest_swing = float(last_absolute_shift.swing_width or 0.0) if last_absolute_shift and last_absolute_shift.swing_width else 0.0
    latest_depth_after = float(last_absolute_shift.depth_after or 0.0) if last_absolute_shift and last_absolute_shift.depth_after else 0.0

    # 🧮 ميزان السولار الصافي: (البداية + المستلم التراكمي) - النهاية المقفلة لايف - الخارج للمعدات الأخرى
    if shifts.exists():
        total_received = sum(float(s.fuel_received or 0.0) for s in shifts)
        
    total_transferred_day = sum(
        float(s.fuel_to_dredger or 0.0) + 
        float(s.fuel_to_excavator or 0.0) + 
        float(s.fuel_to_multicat or 0.0) 
        for s in shifts
    )
    usage = max(0.0, (day_start_fuel + total_received) - day_end_fuel - total_transferred_day) if day_end_fuel > 0 else 0.0

    # 🧮 حساب صافي فروق الماكينات الكلي لليوم بناءً على الفتح وقفل الجلسات الحقيقي
    day_main_h = (m_end_abs - m_start_abs) if m_end_abs >= m_start_abs else 0.0
    day_aux_h = (a_end_abs - a_start_abs) if a_end_abs >= a_start_abs else 0.0

    # 🗺️ ميزان الحد الأقصى المطلق والقاطع لقفل اليوم الهندسي للتقرير الحالي (12:00 ظهراً لليوم التالي)
    from datetime import datetime as dt_class
    limit_report_end = cairo_tz.localize(dt_class.combine(report.date_started + timedelta(days=1), dt_class.min.time())).replace(hour=12)

    # 🔄 محرك الـ Loop لبناء التايم لاين وجدول أداء المشغلين (مطور هندسياً ومنضبط بالثانية)
    if shifts.exists():
        for s in shifts:
            # 🚫 حارس التقرير الفولاذي: يطرد سجل العهدة المعلقة والـ handover من التايم لاين والأداء لراحة العين ومنع التقطيع
            if s.status in ['handover', 'استلاف وتسليم وردية'] or s.stop_reason == "عهدة معلقة بانتظار الاستلام" or "تم استلام الوردية" in str(s.stop_reason):
                continue 

            # 🛡️ حماية العبور التاريخي: لو الوردية بدأت فعلياً بعد الحد الأقصى المطلق للتقرير (12:00 ظهراً لليوم التالي)، تطرد فوراً من الحسبة
            if s.start_time and s.start_time.astimezone(cairo_tz) >= limit_report_end:
                continue

            if s.operator and s.operator.name not in unique_operators:
                unique_operators.append(s.operator.name)

            op_name = s.operator.name if s.operator else "غير محدد"
            if op_name not in op_performance:
                op_performance[op_name] = {'work': 0.0, 'stop': 0.0, 'meters': 0.0}

            # تجميع أمتار التقدم الطولي والمكعبات الصافية بكفاءتها الموزونة
            s_meters = float(s.progress_meters or 0.0)
            op_performance[op_name]['meters'] += s_meters
            total_meters_calc += s_meters

            m3_val = float(s.quantity_m3 or 0.0)
            if m3_val == 0.0 and s.depth_after and s.depth_before:
                m3_val = abs(float(s.depth_after or 0.0) - float(s.depth_before or 0.0)) * s_meters * float(s.swing_width or 0.0)
            total_m3_calc += m3_val

            # 🎯 مقص حماية الظهر الصارم: لو الوردية مفتوحة أو مكملة وتخطت نهاية اليوم الهندسي للتقرير
            eff_end = s.end_time if s.end_time else now
            if eff_end.astimezone(cairo_tz) > limit_report_end:
                # اجبر وقت النهاية في الذاكرة الحين يقف قسراً وصامتاً عند الساعة 12:00 ظهراً المقفلة للتقرير الحالي
                eff_end = limit_report_end

            # حساب المدة الصافية بدقة متناهية وبدون تمدد وهمي عبر الأيام
            dur = (eff_end - s.start_time).total_seconds() / 3600 if s.start_time else 0.0
            if dur < 0: dur = 0.0

            is_active = (s.status == 'active' or s.status == 'تشغيل فعلي (إنتاج)')
            if is_active:
                op_performance[op_name]['work'] += dur
                total_work_dec += dur
            else:
                op_performance[op_name]['stop'] += dur
                total_stop_dec += dur

            # 🗺️ محرك اللحام المطور للأعطال والتشغيل المتتابع بناءً على "تطابق الحالة فقط"
            st_l = s.start_time.astimezone(cairo_tz)
            en_l = eff_end.astimezone(cairo_tz)
            
            # بناء الوصف الفني الصافي للحركة
            clean_reason = f" : {s.stop_reason}" if (s.stop_reason and "تم افتتاح" not in str(s.stop_reason)) else ""
            event_desc = s.get_status_display() + clean_reason
            # 🔍 الفحص الجمركي: لو السجل السابق في التايم لاين له "نفس الحالة الفنية" الحالية
            # قنص وقت النهاية النصي ليعرض 12:00 تماماً لو الوردية مكملة أو تخطت حدود التقرير
            end_str_val = en_l.strftime('%H:%M') if (s.end_time and en_l < limit_report_end) else "12:00"

            if timeline_events and timeline_events[-1]['status'] == s.status:
                prev_event = timeline_events[-1]
                # 🔥 اللحام السحري المتتالي: تمديد وقت النهاية ليصبح نهاية الجلسة الثانية (بحد أقصى 12:00 للتقرير)
                prev_event['end_dt'] = en_l
                prev_event['time_range'] = f"{prev_event['start_dt'].strftime('%H:%M')} - {end_str_val}"
                prev_event['total_dur'] += dur
                prev_event['duration_str'] = to_hhmm(prev_event['total_dur'])
                
                # لحام أسماء المشغلين المشتركين في خط الإنتاج ده بدون تكرار
                if op_name not in prev_event['operators_list']:
                    prev_event['operators_list'].append(op_name)
                
                # دمج أسباب التوقف والملاحظات لو اختلفت شياكة وبدون تكرار
                if s.stop_reason and s.stop_reason != s.get_status_display() and "عهدة معلقة" not in s.stop_reason and "تم افتتاح" not in s.stop_reason:
                    if s.stop_reason not in prev_event['description']:
                        prev_event['description'] += f" | {s.stop_reason}"
            else:
                # لو اختلف الحالة الفنية (مثلاً قلب من تشغيل لعطل)، ينزل كسطر جديد مستقل
                timeline_events.append({
                    'start_dt': st_l, 
                    'end_dt': en_l,
                    'time_range': f"{st_l.strftime('%H:%M')} - {end_str_val}",
                    'description': event_desc, 
                    'status': s.status, 
                    'total_dur': dur, 
                    'duration_str': to_hhmm(dur),
                    'operators_list': [op_name] # حفظ الاسم في لستة للحامها بالأسفل
                })

    # 🤝 اللحام النهائي لأسماء الكباتن المدمجين في جدول التايم لاين لعرض التقرير شياكة للإدارة العليا
    for event in timeline_events:
        event['merged_op_names'] = " / ".join(event['operators_list'])

    # تجهيز جدول الأداء الفردي للمشغلين (يظل كما هو لحفظ حقوق الكباتن بالتفصيل بالخلفية)
    performance_table = []
    for name, data in op_performance.items():
        rate = round(data['meters'] / data['work'], 2) if data['work'] > 0.1 else 0
        performance_table.append({
            'operator': name, 'work_time_str': to_hhmm(data['work']), 'stop_time_str': to_hhmm(data['stop']),
            'meters': data['meters'], 'rate': rate
        })

    # 💎 حماية الأطوال الملوكية اللايف: الاعتماد المطلق على سحب الأطوال من السجل الأحدث المقفل عافية من الجزء الأول
    if latest_floating == 0.0 and first_absolute_shift: 
        latest_floating = float(first_absolute_shift.floating_line or 0.0)
    if latest_land == 0.0 and first_absolute_shift: 
        latest_land = float(first_absolute_shift.land_line or 0.0)

    # 💎 الـ Context الفابريكا الصافي والشامل لحساباتك بالكامل لايف الحين ومحمي 100% ضد التمدد الفلكي للأيام
    context = {
        'report': report, 'performance_table': performance_table, 'timeline': timeline_events, 'unique_operators': unique_operators,
        'total_m3': round(total_m3_calc, 2), 'total_meters': round(total_meters_calc, 1), 'total_work_hours': to_hhmm(total_work_dec), 'total_stop_hours': to_hhmm(total_stop_dec),
        'total_received': total_received, 'fuel_start_val': day_start_fuel, 'fuel_end_val': day_end_fuel, 'total_fuel_usage': round(usage, 2), 'total_transferred': round(total_transferred_day, 2),
        
        'main_engine': {'start': m_start_abs, 'end': m_end_abs, 'net': to_hhmm(day_main_h)},
        'aux_engine': {'start': a_start_abs, 'end': a_end_abs, 'net': to_hhmm(day_aux_h)},
        'start_coords': {'east': start_east_val, 'north': start_north_val},
        'end_coords': {'east': end_east_val, 'north': end_north_val},
        'floating_line': latest_floating, 'land_line': latest_land, 'total_line': latest_floating + latest_land,
        'swing_width': latest_swing, 'depth_after': latest_depth_after
    }
    
    return render(request, 'core/report_detail.html', context)

    
    return render(request, 'core/report_detail.html', context)
@login_required
def quick_action(request, dredger_id, action_type):
    from .models import DailyProjectReport, WorkShift, Staff, Dredger
    from django.shortcuts import render, redirect, get_object_or_404
    from django.utils import timezone
    from datetime import datetime, timedelta
    import pytz

    dredger = get_object_or_404(Dredger, id=dredger_id)
    staff = Staff.objects.filter(user=request.user).first()
    if not staff:
        staff = Staff.objects.first() or Staff.objects.create(name="مدير النظام")

    cairo_tz = pytz.timezone('Africa/Cairo')
    now_l = timezone.now().astimezone(cairo_tz)

    # 💎 القنص المطلق الفابريكا: جلب أحدث سجل في قاعدة البيانات للكراكة
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
    
    # 💎 قنص الحالة والملاحظات الأصلية والـ stop_reason لتوريث الأسباب بدقة
    inherited_status = prev.status if prev else 'inactive'
    inherited_notes = prev.stop_reason if prev else ""

    # لقطة التوجيه الذكي وكسر الدائرة المغلقة برمجياً
    is_delivery_form = request.POST.get('is_delivery_action') == 'true'
    is_already_waiting = (inherited_notes == "عهدة معلقة بانتظار الاستلام") or is_delivery_form

    if request.method == "POST":
        user_date = request.POST.get('action_date')
        user_time = request.POST.get('action_time')
        
        try:
            full_str = f"{user_date} {user_time}"
            event_time = datetime.strptime(full_str, '%Y-%m-%d %H:%M').replace(tzinfo=None)
            event_time = cairo_tz.localize(event_time)
        except (ValueError, TypeError):
            event_time = now_l

        # 🗺️ محرك التوجيه والنقل التاريخي المطور والمأمن 100%
        report_date = event_time.date()
        
        # الفحص الرقمي ليد المشغل: لو الساعة أقل من 12 ظهراً، أو تساوي 12:00 تماماً بالثانية والدقيقة
        if event_time.hour < 12 or (event_time.hour == 12 and event_time.minute == 0):
            report_date -= timedelta(days=1)
            
        # جلب أو إنشاء التقرير المجمع الصحيح لليوم الملحوم هندسياً بناءً على ميزان وقت المشغل
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

        # ✂️ مقص الجلسات اللحظي لغلق الوردية القديمة وحقن عدادات النهاية بالملّي (يظل بكامل كفاءته)
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
            last_open.report_24h = report
            last_open.save()         # 🛡️ ميزان العهدة الفابريكا: قراءة قرار المشغل الفعلي من الشاشة
        form_choice = request.POST.get('status_choice')
        
        # 🎯 محرك التوريث المطلق لسبب التوقف والحالة الأصلية ومنع الـ Default الوهمي
        inherited_stop_reason = ""
        
        if action_type == 'start':
            selected_status = 'active'
        elif action_type == 'handover':
            if is_already_waiting:
                
                # 🔥 ميزان الاختيار الحر الفابريكا: لو المشغل غيّر الحالة بيده من الشاشة، طيع قراره فوراً
                if form_choice and form_choice != 'handover' and form_choice.strip() != "":
                    selected_status = form_choice
                    # جلب سبب التوقف التراجعي للاحتفاظ به في الخلفية
                    second_prev = WorkShift.objects.filter(report_24h__dredger=dredger).exclude(status='handover').order_by('-id').first()
                    inherited_stop_reason = second_prev.stop_reason if second_prev else ""
                else:
                    # 📥 لو سابها فاضية: يرجع للمبدأ البرمجي والتوريث التراجعي الأصلي 100% بدون أي تغيير
                    if inherited_status == 'handover':
                        # حماية تراجعيه لو السجل اللي قبله مباشرة كان كود تسليم، يرجع خطوة كمان لورا لجلب الحالة الحية
                        second_prev = WorkShift.objects.filter(report_24h__dredger=dredger).exclude(status='handover').order_by('-id').first()
                        selected_status = second_prev.status if second_prev else 'other'
                        inherited_stop_reason = second_prev.stop_reason if second_prev else ""
                    else:
                        selected_status = inherited_status
                        # جلب سبب التوقف الأصلي للكراكة قبل لقطة التسليم
                        second_prev = WorkShift.objects.filter(report_24h__dredger=dredger).exclude(status='handover').order_by('-id').first()
                        inherited_stop_reason = second_prev.stop_reason if second_prev else ""
            else:
                # 🤝 لقطة التسليم للكابتن القديم
                selected_status = form_choice if form_choice else 'handover'
        else:
            selected_status = form_choice if form_choice else 'other'

        # ضبط نص الملاحظات وتصفيره تماماً لحظة الاستلام الفعلي
        notes_text = request.POST.get('notes') or ""
        if action_type == 'handover':
            if is_already_waiting:
                # 📥 لقطة الاستلام الفعلي: بنصفر الملاحظات تماماً لتنزل نظيفة، 
                # مع الاحتفاظ بالسبب الفعلي للكراكة لو المشغل سابها موروثة ونفس الحالة
                if form_choice and form_choice != inherited_status and form_choice.strip() != "":
                    # لو غيّر الحالة لعطل جديد مثلاً، يكتب الملاحظة الجديدة اللي كتبها بيده في الفورم
                    notes_text = request.POST.get('notes') or ""
                else:
                    notes_text = inherited_stop_reason if (inherited_stop_reason and "عهدة معلقة" not in inherited_stop_reason) else ""
            else:
                notes_text = "عهدة معلقة بانتظار الاستلام"
        else:
            notes_text = notes_text if notes_text else inherited_stop_reason

        # 🚀 إنشاء الوردية الجارية الجديدة بالطاعة الكاملة لتوريث الحالة الأصلية للكراكة
        new_shift = WorkShift(
            report_24h=report,
            operator=staff,
            status=selected_status, # حقن الحالة المورثة المظبوطة (تشغيل أو العطل الفعلي)
            start_time=event_time,
            fuel_start=current_fuel,
            fuel_end=current_fuel,
            fuel_usage=0.0,
            fuel_to_dredger=0.0,
            fuel_to_excavator=0.0,
            fuel_to_multicat=0.0,
            main_engine_start=current_main,
            main_engine_end=current_main,
            aux_engine_start=current_aux,
            aux_engine_end=current_aux,
            progress_meters=0.0,
            depth_before=current_depth_after,
            depth_after=current_depth_after,
            swing_width=current_swing,
            floating_line=clean_num(request.POST.get('floating_line')) or clean_num(inherited_floating),
            land_line=clean_num(request.POST.get('land_line')) or clean_num(inherited_land),
            start_east=current_east, start_north=current_north, 
            end_east=current_east, end_north=current_north,
            stop_reason=notes_text # حقن السبب الفعلي النظيف لعدم البرجلة في التقرير
        )
        
        new_shift.save()
        return redirect('home')

    # 🔒 رندرة الـ Context وتمرير الختم الجمركي للـ HTML
    context = {
        'dredger': dredger,
        'action_type': action_type,
        'current_date': now_l.strftime('%Y-%m-%d'),
        'current_time': now_l.strftime('%H:%M'),
        'inherited': {
            'fuel': clean_num(inherited_fuel), 
            'main': clean_num(inherited_main), 
            'aux': clean_num(inherited_aux),
            'depth': clean_num(inherited_depth), 
            'east': inherited_east, 
            'north': inherited_north,
            'floating': inherited_floating, 
            'land': inherited_land, 
            'swing': inherited_swing,
            'status_code': inherited_status, 
            'notes': inherited_notes
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
        # ⛽ المعادلة الرياضية الفولاذية لصافي حرق السولار الفعلي للوردية بعد خصم المنقول الثلاثي
        f_start = float(s.fuel_start or 0.0)
        f_rec = float(s.fuel_received or 0.0)
        f_end = float(s.fuel_end or 0.0)
        
        # قنص وتجميع قيم المنقول الثلاثة المسجلة للوردية لمنع ظلم شيفت B
        f_trans = (
            float(s.fuel_to_dredger or 0.0) + 
            float(s.fuel_to_excavator or 0.0) + 
            float(s.fuel_to_multicat or 0.0)
        )
        
        # إذا سجل قفل الوردية، يحسب الحرق الفعلي الصافي، لو جارية يحسب صفر
        if f_end > 0.0:
            fuel_val = max(0.0, (f_start + f_rec) - f_end - f_trans)
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

@login_required
def reports_list(request):
    from .models import DailyProjectReport, PipeFighterOperations, WorkShift, Dredger, Staff
    from django.utils import timezone
    import pytz
    
    cairo_tz = pytz.timezone('Africa/Cairo')
    now_local = timezone.now().astimezone(cairo_tz)
    today_date = now_local.date()
    
    # 👑 محرك الإنعاش الآلي المطور والمشروط بالوردية الحية:
    # السيستم الحين هيلف فقط على الورديات الحية المفتوحة حالياً (التشغيل الجاري لايف الحين)
    open_shifts = WorkShift.objects.filter(end_time__isnull=True).select_related('report_24h__dredger')
    
    for s in open_shifts:
        if s.report_24h and s.report_24h.dredger:
            dr = s.report_24h.dredger
            
            # الفحص: لو الساعة الحالية تخطت 12:00 ظهراً، والوردية المفتوحة لسه مربوطة باليوم السابق
            if now_local.hour >= 12 and s.report_24h.date_started < today_date:
                # 1. خلق تقرير اليوم الجديد الحاضر للكراكة الشغالة دي فقط لا غير (تطايرت الكراكات الميتة)
                new_report, _ = DailyProjectReport.objects.get_or_create(dredger=dr, date_started=today_date)
                
                # 2. اللحام السحري: نقل الوردية الجارية حالياً جراحياً لترتبط بالتقرير الجديد فوراً
                # لكي تشحن الـ 9000 لتر والعدادات والأعماق لايف جوه تقرير النهارده وتطير الأصفار!
                s.report_24h = new_report
                s.save()

    # 🟢 كود الجلب والعرض الأصلي الفابريكا القديم بتاعك يكمل تحت هنا بالملّي كما هو بدون تغيير:
    all_reports = DailyProjectReport.objects.all().order_by('-date_started')
    pipe_reports = PipeFighterOperations.objects.all().order_by('-date')

    print(f"عدد تقارير الكراكات: {all_reports.count()}")

    context = {
        'reports': all_reports,    # الاسم المعتمد 'reports'
        'pipe_ops': pipe_reports   # الاسم المعتمد 'pipe_ops'
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
def start_marine_inventory(request, dredger_id):
    from .models import InventoryItem, MarineInventoryReport, MarineInventoryDetail, Staff, Dredger
    from django.utils import timezone
    from django.shortcuts import render, redirect, get_object_or_404

    # ⚓ 1. الحسم الهيدروليكي المطلق: قنص الكراكة الحقيقية بالـ ID الممرر من الرابط مباشرة لمنع التداخل
    current_dredger = get_object_or_404(Dredger, id=dredger_id)

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
        # 3. فرض الحفظ الإجباري المباشر لاسم الكراكة الحقيقية المحددة في التقرير
        report = MarineInventoryReport.objects.create(
            operator=staff,
            report_type='marine',
            notes=request.POST.get('notes', ''),
            dredger=current_dredger  # الحقن المباشر للكراكة الصحيحة
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

        # 🔥 التوجيه المطور والموزون: يرحل المشغل لأرشيف الجرد الخاص بنفس الكراكة دي بالذات
        return redirect('marine_inventory_list', dredger_id=current_dredger.id)

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


@login_required
def marine_inventory_list(request, dredger_id):
    # استدعاء موضعي ذكي ومحدث للموديلات لربط الكراكة والأرشيف
    from .models import MarineInventoryReport, Dredger
    from django.shortcuts import render, get_object_or_404

    # ⚓ 1. قنص الكراكة الحقيقية المحددة بالـ ID الممرر من الرابط لمنع التداخل وسحب الاسم الغلط
    dredger = get_object_or_404(Dredger, id=dredger_id)

    # 📊 2. فلترة تقارير أرشيف البحرية لتجلب فقط وحصرياً التقارير الخاصة بهذه الكراكة بالذات زمنيًا
    reports = MarineInventoryReport.objects.filter(
        dredger=dredger, 
        report_type='marine'
    ).order_by('-date')
    
    # تمرير كائن الكراكة والأرشيف الصافي المفلتر للـ HTML
    context = {
        'dredger': dredger,
        'reports': reports
    }
    return render(request, 'core/marine_inventory_list.html', context)


@login_required
def close_report_permanently(request, report_id):
    # الحماية: فقط السوبر أدمن هو من يملك صلاحية صب التقرير وتجميده
    if not request.user.is_superuser:
        messages.error(request, "⚠️ عذراً كابتن، صلاحية اعتماد وإغلاق التقارير للأبد محصورة لمدير النظام فقط.")
        return redirect('report_detail', report_id=report_id)

    report = get_object_or_404(DailyProjectReport, id=report_id)
    shifts = report.shifts.all().order_by('start_time')
    
    # تنفيذ معادلات التجميع لآخر مرة بالملّي
    def to_hhmm(decimal_hours):
        if not decimal_hours or decimal_hours < 0: return "00:00"
        total_mins = int(round(decimal_hours * 60))
        hrs, mins = divmod(total_mins, 60)
        return f"{hrs:02d}:{mins:02d}"

    total_work_dec, total_stop_dec, day_main_h, day_aux_h, total_m3_calc = 0.0, 0.0, 0.0, 0.0, 0.0
    now = timezone.now()

    for s in shifts:
        if s.status in ['handover', 'استلام وتسليم وردية']:
            continue
        eff_end = s.end_time if s.end_time else now
        dur = (eff_end - s.start_time).total_seconds() / 3600 if s.start_time else 0.0

        if s.status == 'active' or s.status == 'تشغيل فعلي (إنتاج)':
            total_work_dec += dur
        else:
            total_stop_dec += dur

        day_main_h += float(s.main_engine_hours or 0.0)
        day_aux_h += float(s.aux_engine_hours or 0.0)
        
        m3_val = float(s.quantity_m3 or 0.0)
        if m3_val == 0.0 and s.depth_after and s.depth_before:
            m3_val = abs(float(s.depth_after or 0.0) - float(s.depth_before or 0.0)) * float(s.progress_meters or 0.0) * float(s.swing_width or 0.0)
        total_m3_calc += m3_val

    first_s = shifts.first()
    last_s = shifts.last()
    total_received = sum(float(s.fuel_received or 0.0) for s in shifts)
    day_start_fuel = first_s.fuel_start if first_s else 0.0
    day_end_fuel = last_s.fuel_end if (last_s and last_s.fuel_end > 0) else 0.0
    usage = (day_start_fuel + total_received) - day_end_fuel if day_end_fuel > 0 else 0.0

    # 🔒 صبّ الخرسانة وتجميد الأرقام في الجدول للأبد
    report.frozen_total_m3 = round(total_m3_calc, 2)
    report.frozen_total_meters = sum(s.progress_meters for s in shifts)
    report.frozen_work_hours = to_hhmm(total_work_dec)
    report.frozen_stop_hours = to_hhmm(total_stop_dec)
    report.frozen_fuel_usage = round(usage, 2)
    report.frozen_main_net = to_hhmm(day_main_h)
    report.frozen_aux_net = to_hhmm(day_aux_h)
    
    report.is_closed = True # قفل رسمي مشفر لليوم
    report.save()

    messages.success(request, f"🔒 تم اعتماد وصبّ تقرير اليوم {report.date_started} بنجاح، وتجميد الأرقام للأبد!")
    return redirect('report_detail', report_id=report.id)

@login_required
def raise_emergency_alert(request):
    from .models import EmergencyAlert, Staff, Dredger
    from django.shortcuts import redirect, get_object_or_404
    from django.contrib import messages
    
    if request.method == "POST":
        dredger_id = request.POST.get('dredger_id')
        alert_type = request.POST.get('alert_type')
        
        # قنص الشخص الحالي مسجل الدخول (سواء بحري، بايب فيتر، أو مهندس إدارة)
        staff = Staff.objects.filter(user=request.user).first()
        
        if not dredger_id or not alert_type:
            messages.error(request, "🚨 خطأ: من فضلك اختر الكراكة ونوع البلاغ أولاً.")
            return redirect('home')
            
        # 🎯 قنص الكراكة المحددة بقرار المبلّغ من الشاشة صراحة وبدون تخمين
        target_dredger = get_object_or_404(Dredger, id=dredger_id)
        
        # صب البلاغ الفوري لايف على الكراكة المحددة
        EmergencyAlert.objects.create(
            dredger=target_dredger,
            operator=staff,
            alert_type=alert_type,
            is_resolved=False
        )
        
        messages.success(request, f"🚀 تم إرسال البلاغ العاجل لكراكة ({target_dredger.name}) بنجاح وجاري إخطار الإدارة!")
        return redirect('home')
        
    return redirect('home')

@login_required
def resolve_emergency_alert(request, alert_id):
    """
    ✅ دالة إغلاق البلاغ: تحول حالة العطل لـ تم الإصلاح ليختفي من كارت الكراكة فوراً
    """
    from .models import EmergencyAlert
    from django.shortcuts import get_object_or_404, redirect
    from django.contrib import messages
    
    # قنص البلاغ بالـ ID الخاص به عافية
    alert = get_object_or_404(EmergencyAlert, id=alert_id)
    
    # تغيير الحالة في الخزنة الحديدية
    alert.is_resolved = True
    alert.save()
    
    messages.success(request, "✅ تم تسجيل إصلاح العطل بنجاح وإعادة الكراكة للوضع الطبيعي.")
    return redirect('home')

from django.contrib.auth.decorators import user_passes_test
import datetime

def is_management(user):
    return user.is_active and (user.is_staff or user.is_superuser)

@login_required
@user_passes_test(is_management, login_url='home', redirect_field_name=None)
def procurement_dashboard(request):
    from .models import ProcurementOrder, Staff
    from django.shortcuts import get_object_or_404
    
    # 📥 محرك الاستقبال المطور: فرز الطلبات القادمة (مأمن تماماً لحسابات الإدمن والمشغلين)
    if request.method == 'POST':
        action = request.POST.get('action')
        
        # أ. تسجيل طلب شراء جديد (متاح للـ Admin ولجميع المشغلين لايف)
        if action == 'create':
            item_name = request.POST.get('item_name')
            quantity = request.POST.get('quantity')
            admin_notes = request.POST.get('admin_notes', '')
            
            # قنص حساب المشغل الفعلي لو موجود
            staff = Staff.objects.filter(user=request.user).first()
            
            # 🟢 تم التحرير الهندسي الحين: الحفظ مشروط فقط بوجود الاسم والكمية، والـ staff اختياري لمنع الـ None كراش
            if item_name and quantity:
                ProcurementOrder.objects.create(
                    item_name=item_name,
                    quantity=quantity,
                    requested_by=staff, # هينزل باسمك لو مشغل، ولو إدمن هينزل فاضي ويكتب بره الإدارة
                    status='pending',
                    admin_notes=admin_notes,
                    estimated_cost=0.0
                )
        
        # ب. تحديث الحالة (للإدارة فقط)
        elif action == 'update_status' and (request.user.is_staff or request.user.is_superuser):
            order_id = request.POST.get('order_id')
            new_status = request.POST.get('new_status')
            order = get_object_or_404(ProcurementOrder, id=order_id)
            order.status = new_status
            
            # تسجيل تواريخ التنفيذ والاستلام ديناميكياً بناءً على الحالة الجديدة
            from django.utils import timezone
            if new_status == 'purchased':
                order.date_executed = timezone.now().date()
            elif new_status == 'delivered':
                order.date_delivered = timezone.now().date()
            order.save()
            
        # ج. حذف الطلب نهائياً (للإدارة فقط)
        elif action == 'delete_order' and (request.user.is_staff or request.user.is_superuser):
            order_id = request.POST.get('order_id')
            order = get_object_or_404(ProcurementOrder, id=order_id)
            order.delete()

        return redirect('procurement_dashboard')

    # 🔍 محرك الفرز التاريخي
    orders = ProcurementOrder.objects.all().select_related('requested_by')
    start_date_str = request.GET.get('start_date')
    end_date_str = request.GET.get('end_date')
    status_filter = request.GET.get('status')
    
    if start_date_str: orders = orders.filter(date_requested__gte=start_date_str)
    if end_date_str: orders = orders.filter(date_requested__lte=end_date_str)
    if status_filter: orders = orders.filter(status=status_filter)
        
    pending_count = orders.filter(status='pending').count()
    purchased_count = orders.filter(status='purchased').count()
    delivered_count = orders.filter(status='delivered').count()
    
    context = {
        'orders': orders, 'pending_count': pending_count, 'purchased_count': purchased_count,
        'delivered_count': delivered_count, 'start_date': start_date_str or "",
        'end_date': end_date_str or "", 'current_status': status_filter or ""
    }
    return render(request, 'core/procurement_dashboard.html', context)