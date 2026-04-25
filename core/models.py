from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import time, timedelta

# 1. دليل الموظفين
class Staff(models.Model):
    GROUP_CHOICES = [('A', 'مجموعة A'), ('B', 'مجموعة B')]
    TEAM_TYPE = [('dredger', 'طاقم كراكة'), ('pipe', 'طاقم خط بحري')]
    ROLE_CHOICES = [
        ('operator', 'مشغل'),
        ('marine', 'بحرية'),
        ('mechanic', 'ميكانيكا'),
        ('admin', 'إداري/سائق'),
    ]

    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="حساب المستخدم")
    name = models.CharField(max_length=100, verbose_name="الاسم بالكامل")
    group = models.CharField(max_length=1, choices=GROUP_CHOICES, verbose_name="المجموعة (الوردية)")
    team_type = models.CharField(max_length=10, choices=TEAM_TYPE, verbose_name="نوع الطاقم")
    role = models.CharField(max_length=30, choices=ROLE_CHOICES, verbose_name="الوظيفة")
    phone = models.CharField(max_length=15, verbose_name="رقم الهاتف", null=True, blank=True)

    class Meta:
        verbose_name = "موظف"
        verbose_name_plural = "دليل الموظفين"

    def __str__(self):
        return f"{self.name} - {self.get_group_display()}"

# 2. الكراكات
class Dredger(models.Model):
    name = models.CharField(max_length=100, verbose_name="اسم الكراكة")
    allowed_operators = models.ManyToManyField(User, blank=True, verbose_name="المشغلين المسموح لهم")
    vessel_phone = models.CharField(max_length=20, default="01XXXXXXXXX", verbose_name="تليفون الكراكة")
    is_active = models.BooleanField(default=True, verbose_name="في الخدمة")
    fuel_capacity = models.FloatField(default=0, verbose_name="سعة خزان الكراكة (لتر)")
    stock_fuel = models.FloatField(default=0, verbose_name="السولار المتاح في الاستوك (لتر)")


    class Meta:
        verbose_name = "كراكة"
        verbose_name_plural = "الكراكات"

    def __str__(self): return self.name

# 3. التقرير اليومي المجمع
class DailyProjectReport(models.Model):
    dredger = models.ForeignKey(Dredger, on_delete=models.CASCADE, verbose_name="الكراكة")
    date_started = models.DateField(verbose_name="تاريخ يوم العمل")
    is_closed = models.BooleanField(default=False, verbose_name="تم إغلاق اليوم")

    class Meta:
        verbose_name = "تقرير يومي مجمع"
        verbose_name_plural = "التقارير اليومية المجمعة"

    def __str__(self): return f"{self.dredger.name} - {self.date_started}"

class WorkShift(models.Model):
    SHIFT_TYPE = [('morning', 'صباحي (نهار)'), ('night', 'مسائي (ليل)')]
    fuel_added = models.FloatField(default=0, verbose_name="سولار مضاف للكراكة (تموين)")
    
    # قائمة الحالات الجديدة والمفصلة
    STATUS_CHOICES = [
        ('active', 'في الخدمة (تكريك فعلي)'),
        ('maint_plan', 'توقف للصيانة الدورية'),
        ('anchors', 'توقف لنقل المخاطيف'),
        ('pipe_line', 'توقف لصيانة خط الطرد'),
        ('water_pump', 'توقف تكريك لضخ مياه في الخط'),
        ('shifting', 'توقف لتشفيت الكراكة'),
        ('wire_break', 'توقف لانقطاع واير'),
        ('breakdown', 'توقف لعطل فني مفاجئ'),
        ('basin', 'توقف بسبب حوض الترسيب'),
        ('other', 'توقف لأسباب أخرى'),
    ]

    # ... باقي الحقول كما هي ...


    report_24h = models.ForeignKey(DailyProjectReport, on_delete=models.CASCADE, related_name='shifts', null=True, blank=True, verbose_name="اليوم المرتبط")
    operator = models.ForeignKey(Staff, on_delete=models.SET_NULL, null=True, verbose_name="المشغل")
    shift_time = models.CharField(max_length=10, choices=SHIFT_TYPE, verbose_name="فترة الوردية", null=True, blank=True)
    
    # التوقيت: جعلناه يسجل لحظة الضغط تلقائياً
    start_time = models.DateTimeField(default=timezone.now, verbose_name="وقت الاستلام/البدء")
    end_time = models.DateTimeField(null=True, blank=True, verbose_name="وقت التسليم/التوقف")
    
    # الإحداثيات: جعلناها اختيارية (blank=True) لكي لا ينهار السيستم عند ضغطة الزر الأولى
    start_east = models.FloatField(null=True, blank=True, verbose_name="E البداية")
    start_north = models.FloatField(null=True, blank=True, verbose_name="N البداية")
    end_east = models.FloatField(null=True, blank=True, verbose_name="E النهاية")
    end_north = models.FloatField(null=True, blank=True, verbose_name="N النهاية")

    quantity_m3 = models.FloatField(default=0, verbose_name="الكمية المكعبة")
    progress_meters = models.FloatField(default=0, verbose_name="أمتار التقدم (من الخريطة)")
    depth = models.FloatField(default=0, verbose_name="العمق")

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', verbose_name="الحالة")
    # داخل كلاس WorkShift في models.py
    # ... الحقول السابقة ...
    floating_line = models.FloatField(default=0, verbose_name="طول الخط العائم (م)")
    land_line = models.FloatField(default=0, verbose_name="طول الخط الأرضي (م)")

    @property
    def total_line_length(self):
        return (self.floating_line or 0) + (self.land_line or 0)

    
    # الأعطال
    stop_reason = models.TextField(null=True, blank=True, verbose_name="سبب التوقف")
    stop_image = models.ImageField(upload_to='stops/%Y/%m/', null=True, blank=True, verbose_name="صورة التوقف")

    # الماكينات: أضفت لك الماكينة المساعدة كما طلبت
    main_engine_hours = models.FloatField(default=0, verbose_name="ساعات الماكينة الرئيسية")
    aux_engine_hours = models.FloatField(default=0, verbose_name="ساعات الماكينة المساعدة") # حقل جديد
    fuel_usage = models.FloatField(default=0, verbose_name="السولار المستهلك")

    class Meta:
        verbose_name = "سجل وردية"
        verbose_name_plural = "سجلات الورديات (Live)"

    def __str__(self):
        return f"{self.operator if self.operator else 'بدون اسم'} - {self.start_time.strftime('%Y-%m-%d %H:%M')}"
    
    # داخل كلاس WorkShift في models.py
    # --- حقول السولار الجديدة ---
    fuel_start = models.FloatField(default=0, verbose_name="كمية السولار بداية الوردية (لتر)")
    fuel_end = models.FloatField(default=0, verbose_name="كمية السولار نهاية الوردية (لتر)")
    fuel_received = models.FloatField(default=0, verbose_name="السولار المستلم/تموين (لتر)")
    # حقل fuel_usage سيصبح مخفياً أو للقراءة فقط ويحسبه السيستم

    # --- حقول المحركات الجديدة ---
    main_engine_start = models.FloatField(default=0, verbose_name="ساعة الماكينة الرئيسية (بداية)")
    main_engine_end = models.FloatField(default=0, verbose_name="ساعة الماكينة الرئيسية (نهاية)")
    
    aux_engine_start = models.FloatField(default=0, verbose_name="ساعة الماكينة المساعدة (بداية)")
    aux_engine_end = models.FloatField(default=0, verbose_name="ساعة الماكينة المساعدة (نهاية)")

    # وظيفة الحفظ التلقائي للنتائج
    def save(self, *args, **kwargs):
        # 1. حساب استهلاك السولار: (البداية + المستلم) - النهاية
        self.fuel_usage = (self.fuel_start + self.fuel_received) - self.fuel_end
        
        # 2. حساب ساعات تشغيل المحركات
        # ملاحظة: سيظل حقل main_engine_hours و aux_engine_hours موجودين لتخزين النتيجة
        self.main_engine_hours = self.main_engine_end - self.main_engine_start
        self.aux_engine_hours = self.aux_engine_end - self.aux_engine_start
        
        super().save(*args, **kwargs)
    # داخل كلاس WorkShift في models.py
    def save(self, *args, **kwargs):
        # حساب الساعات: فقط إذا كانت هناك قراءة نهاية
        if self.main_engine_end > 0:
            self.main_engine_hours = self.main_engine_end - self.main_engine_start
        else:
            self.main_engine_hours = 0
            
        if self.aux_engine_end > 0:
            self.aux_engine_hours = self.aux_engine_end - self.aux_engine_start
        else:
            self.aux_engine_hours = 0

        # حساب السولار: لا يحسب استهلاكاً طالما لم يتم إدخال "سولار نهاية الوردية"
        if self.fuel_end > 0:
            # المعادلة: (البداية + التموين) - النهاية
            self.fuel_usage = (self.fuel_start + self.fuel_received) - self.fuel_end
        else:
            # إذا لم يسجل النهاية بعد، الاستهلاك = 0 (وردية جارية)
            self.fuel_usage = 0
            
        super().save(*args, **kwargs)


# 5. الـ Pipe Fighter
class PipeFighterOperations(models.Model):
    date = models.DateField(auto_now_add=True, verbose_name="التاريخ")
    shift = models.CharField(max_length=10, choices=[('morning', 'نهار'), ('night', 'ليل')], verbose_name="الوردية")
    operator_in_charge = models.ForeignKey(Staff, on_delete=models.SET_NULL, null=True, limit_choices_to={'team_type': 'pipe'}, verbose_name="المشغل المسؤول")
    crew_present = models.ManyToManyField(Staff, related_name='pf_present', verbose_name="الطاقم الحاضر")
    total_line_length = models.FloatField(verbose_name="طول الخط")
    active_joints = models.IntegerField(verbose_name="الوصلات")
    spare_pipes = models.IntegerField(default=0, verbose_name="مواسير احتياطي")
    scrapped_pipes = models.IntegerField(default=0, verbose_name="مواسير هالك")
    work_photos = models.ImageField(upload_to='pf_daily/', null=True, blank=True, verbose_name="صور العمل")

    class Meta:
        verbose_name = "تقرير خط بحري"
        verbose_name_plural = "تقارير الخطوط البحرية"

# 6. الشريط الإخباري
class NewsTicker(models.Model):
    message = models.CharField(max_length=500, verbose_name="التعليمات / الخبر")
    is_active = models.BooleanField(default=True, verbose_name="تفعيل")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "شريط أخبار"
        verbose_name_plural = "أشرطة الأخبار"

# 7. المخازن
class InventoryItem(models.Model):
    name = models.CharField(max_length=100, verbose_name="اسم الصنف")
    quantity = models.IntegerField(default=0, verbose_name="الكمية")
    price = models.DecimalField(max_digits=10, decimal_places=2, verbose_name="السعر")

    class Meta:
        verbose_name = "صنف مخزني"
        verbose_name_plural = "المخازن"

class AdminVault(models.Model):
    staff_name = models.CharField(max_length=100, verbose_name="اسم الموظف")
    username = models.CharField(max_length=50, verbose_name="اسم المستخدم")
    password_plain = models.CharField(max_length=50, verbose_name="كلمة المرور (للتذكير)")
    notes = models.TextField(null=True, blank=True, verbose_name="ملاحظات إضافية")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "سجل حساب سري"
        verbose_name_plural = "خزنة الحسابات السرية"

    def __str__(self):
        return f"حساب: {self.staff_name}"

class WeeklyRotation(models.Model):
    GROUP_CHOICES = [('A', 'مجموعة A هي العاملة'), ('B', 'مجموعة B هي العاملة')]
    start_date = models.DateField(verbose_name="تاريخ بداية الأسبوع (الأربعاء)")
    active_group = models.CharField(max_length=1, choices=GROUP_CHOICES, verbose_name="المجموعة النشطة")

    class Meta:
        verbose_name = "دوران الورديات الأسبوعي"
        verbose_name_plural = "دوران الورديات الأسبوعي"

    def __str__(self):
        return f"أسبوع {self.start_date} - {self.get_active_group_display()}"
