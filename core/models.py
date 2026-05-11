from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from datetime import time, timedelta
from django.core.exceptions import ValidationError
import pytz
# 1. دليل الموظفين
class Staff(models.Model):
    GROUP_CHOICES = [('A', 'مجموعة A'), ('B', 'مجموعة B'),('office', 'الإدارة'),('other', 'أخرى')]
    TEAM_TYPE = [('dredger', 'طاقم كراكة'), ('pipe_fighter', 'طاقم خط بحري'),('admin', 'الإدارة'),('other', 'أخرى')]
    ROLE_CHOICES = [
        ('engineer', 'مهندس'), # الخيار الجديد
        ('supervisor', 'مشرف'), # الخيار الجديد
        ('manager', 'مدير مشروع'),
        ('operator', 'مشغل'),
        ('marine', 'بحرية'),
        ('mechanic', 'ميكانيكا'),
        ('admin', 'إداري/سائق'),
    ]

    user = models.OneToOneField(User, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="حساب المستخدم")
    name = models.CharField(max_length=100, verbose_name="الاسم بالكامل")
    group = models.CharField(max_length=10, choices=GROUP_CHOICES, verbose_name="المجموعة (الوردية)")
    team_type = models.CharField(max_length=20, choices=TEAM_TYPE, verbose_name="نوع الطاقم")
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
    fuel_received = models.FloatField(default=0, verbose_name="سولار مستلم")

    STATUS_CHOICES = [
        ('active', 'تشغيل فعلي (إنتاج)'),
        ('breakdown_mech', 'عطل ميكانيكي'),
        ('breakdown_elec', 'عطل كهربائي'),
        ('maintenance', 'صيانة دورية / عمرة'),
        ('anchors', 'نقل مخاطيف'),
        ('maneuver', 'مناورة / تغيير موقع'),
        ('pipeline', 'فك / تركيب / إصلاح خط الطرد'),
        ('weather', 'توقف بسبب سوء الأحوال الجوية'),
        ('waiting_barge', 'انتظار صندل / تموين'),
        ('safety', 'توقف لأسباب تتعلق بالسلامة'),
        ('inspection', 'تفتيش / زيارة رسمية'),
        ('handover', 'استلام وتسليم وردية'),
        ('other', 'توقف لأسباب أخرى'),
    ]

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='active', verbose_name="الحالة")
    # ... باقي الحقول كما هي ...

    def clean(self):
        super().clean()
        if self.start_time and self.end_time:
            # توقيت القاهرة الفاصل لليوم
            cairo_tz = pytz.timezone('Africa/Cairo')
            start_local = self.start_time.astimezone(cairo_tz)
            end_local = self.end_time.astimezone(cairo_tz)

            # تحديد 12 ظهراً الخاصة بيوم البدء
            limit_noon = start_local.replace(hour=12, minute=0, second=0, microsecond=0)

            # إذا بدأت قبل الظهر وحاول ينهي بعد الظهر في نفس السجل
            if start_local < limit_noon and end_local > limit_noon:
                raise ValidationError(
                    "خطأ فني: لا يمكن للسجل تخطي الساعة 12:00 ظهراً. "
                    "من فضلك اجعل وقت النهاية 12:00 تماماً لهذا السجل، "
                    "ثم افتح سجلاً جديداً لما بعد الساعة 12."
                )
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
    depth_before = models.FloatField(default=0.0, verbose_name="العمق قبل التكريك (م)")
    depth_after = models.FloatField(default=0.0, verbose_name="العمق بعد التكريك (م)")
    swing_width = models.FloatField(default=0.0, verbose_name="عرض السوينج (م)")

    def save(self, *args, **kwargs):
        # معادلة الحساب: (الفرق بين العمقين) × التقدم × عرض السوينج
        depth_diff = abs(self.depth_after - self.depth_before)
        self.quantity_m3 = round(depth_diff * (self.progress_meters or 0) * (self.swing_width or 0), 2)
        super().save(*args, **kwargs)
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


class PipeFighterOperations(models.Model):
    SHIFT_CHOICES = [('morning', 'صباحي'), ('night', 'مسائي')]

    # بيانات أساسية
    date = models.DateField(auto_now_add=True, verbose_name="التاريخ")
    shift = models.CharField(max_length=10, choices=SHIFT_CHOICES, verbose_name="الوردية")
    operator_in_charge = models.ForeignKey('Staff', on_delete=models.SET_NULL, null=True, verbose_name="المسؤول")

    # 1. الخط العائم (بالخدمة حالياً)
    float_pipes = models.IntegerField(default=0, verbose_name="مواسير عائمة (عدد)")
    float_rubbers = models.IntegerField(default=0, verbose_name="ربرات عائمة (عدد)")
    float_pontoons = models.IntegerField(default=0, verbose_name="طوافات الخط (عدد)")
    float_pantons = models.IntegerField(default=0, verbose_name="بانتون (عدد)")
    float_anchors = models.IntegerField(default=0, verbose_name="مخاطيف الخط (عدد)")
    float_length = models.FloatField(default=0, editable=False, verbose_name="طول الخط العائم")

    # 2. الخط الأرضي (بالخدمة حالياً)
    land_pipes = models.IntegerField(default=0, verbose_name="مواسير أرضية (عدد)")
    land_rubbers = models.IntegerField(default=0, verbose_name="ربرات أرضية (عدد)")
    land_length = models.FloatField(default=0, editable=False, verbose_name="طول الخط الأرضي")

    total_line_length = models.FloatField(default=0, editable=False, verbose_name="إجمالي طول الخط")

    # 3. قسم الاستوك والمخزن (الطلب الجديد)
    # استوك المواسير
    stock_pipes_new = models.IntegerField(default=0, verbose_name="مواسير جديدة")
    stock_pipes_used = models.IntegerField(default=0, verbose_name="مواسير مستعملة صالحة")
    stock_pipes_scrap = models.IntegerField(default=0, verbose_name="مواسير هالك")

    # استوك الربرات
    stock_rubbers_new = models.IntegerField(default=0, verbose_name="ربرات جديدة")
    stock_rubbers_used = models.IntegerField(default=0, verbose_name="ربرات مستعملة صالحة")
    stock_rubbers_scrap = models.IntegerField(default=0, verbose_name="ربرات هالك")

    # استوك الطوافات
    stock_pontoons_new = models.IntegerField(default=0, verbose_name="طوافات جديدة")
    stock_pontoons_used = models.IntegerField(default=0, verbose_name="طوافات مستعملة صالحة")
    stock_pontoons_scrap = models.IntegerField(default=0, verbose_name="طوافات هالك")

    # 4. المهمات والأدوات
    bolts_30 = models.IntegerField(default=0, verbose_name="مسامير 30مم")
    bolts_27 = models.IntegerField(default=0, verbose_name="مسامير 27مم")
    wrench_30 = models.IntegerField(default=0, verbose_name="مفتاح 30")
    wrench_27 = models.IntegerField(default=0, verbose_name="مفتاح 27")
    socket_30 = models.IntegerField(default=0, verbose_name="لقمة 30مم")
    socket_27 = models.IntegerField(default=0, verbose_name="لقمة 27مم")
    air_gun = models.IntegerField(default=0, verbose_name="ايرجن (عدد)")
    
    # 5. قسم الأصناف الإضافية (مرونة الإضافة)
    # ده موديل فرعي هنربطه تحت، بس هنسيب هنا حقل للملاحظات العامة
    work_description = models.TextField(verbose_name="بيان الأعمال والملاحظات", blank=True, null=True)
    work_photos = models.ImageField(upload_to='pipe_fighter/', verbose_name="صور العمل", blank=True, null=True)

    def save(self, *args, **kwargs):
        # حساب الأطوال أوتوماتيكياً عند كل حفظ
        self.float_length = (self.float_pipes * 12) + (self.float_rubbers * 1.5)
        self.land_length = (self.land_pipes * 12) + (self.land_rubbers * 1.5)
        self.total_line_length = self.float_length + self.land_length
        super().save(*args, **kwargs)

    class Meta:
        verbose_name = "تقرير بايب فايتر"
        verbose_name_plural = "تقارير بايب فايتر"

# 6. الموديل الجديد لإضافة أصناف بحرية متغيرة (عشان يقدر يضيف أصناف براحته)
class PipeFighterExtraItem(models.Model):
    report = models.ForeignKey(PipeFighterOperations, on_delete=models.CASCADE, related_name='extra_items')
    item_name = models.CharField(max_length=100, verbose_name="اسم الصنف الإضافي")
    quantity = models.IntegerField(default=0, verbose_name="الكمية")

    class Meta:
        verbose_name = "صنف إضافي بالخط"
        verbose_name_plural = "أصناف إضافية بالخط"

# 6. الشريط الإخباري
class NewsTicker(models.Model):
    message = models.CharField(max_length=500, verbose_name="التعليمات / الخبر")
    is_active = models.BooleanField(default=True, verbose_name="تفعيل")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "شريط أخبار"
        verbose_name_plural = "أشرطة الأخبار"

# 7. المخازن
# أضف هذا في core/models.py

class InventoryCategory(models.TextChoices):
    BELTS = 'قايش', 'قايش'
    LOCKS = 'أقفال', 'أقفال'
    ROPES = 'حبال', 'حبال'
    BOLTS = 'مسامير', 'مسامير'
    WIRES = 'وايرات', 'وايرات'
    TOOLS = 'مفاتيح ولقم', 'مفاتيح ولقم'
    RUBBERS = 'ربرات', 'ربرات'
    PONTOONS = 'طوافات', 'طوافات'
    OTHER = 'أخرى', 'أخرى'
    # (ملاحظة: شلنا المواسير بناءً على طلبك من جرد البحرية)

# في core/models.py

class InventoryItem(models.Model):
    LOCATION_CHOICES = [
        ('site', 'مخزن الموقع (البر)'),
        ('marine', 'مخزن البحرية (الكراكة)'),
    ]
    name = models.CharField(max_length=100, verbose_name="اسم الصنف")
    category = models.CharField(max_length=50, choices=InventoryCategory.choices, verbose_name="القسم")
    quantity = models.FloatField(default=0, verbose_name="الرصيد الحالي")
    # تأكد من وجود هذا السطر تحديداً:
    location = models.CharField(max_length=20, choices=LOCATION_CHOICES, default='site', verbose_name="مكان التواجد")

    def __str__(self):
        return f"{self.name} ({self.get_location_display()})"



# موديل جرد بحرية الكراكة (التقرير الأسبوعي المنفصل)
class MarineInventoryReport(models.Model):
    date = models.DateTimeField(default=timezone.now, verbose_name="تاريخ وساعة الجرد")
    operator = models.ForeignKey('Staff', on_delete=models.CASCADE, verbose_name="المشغل المسؤول")
    notes = models.TextField(blank=True, null=True, verbose_name="ملاحظات الجرد")

    class Meta:
        verbose_name = "جرد مخزن البحرية"
        verbose_name_plural = "تقارير جرد البحرية الأسبوعية"

    def __str__(self):
        return f"جرد بحرية بتاريخ {self.date.strftime('%Y-%m-%d')}"

class MarineInventoryDetail(models.Model):
    report = models.ForeignKey(MarineInventoryReport, on_delete=models.CASCADE, related_name='details')
    item = models.ForeignKey(InventoryItem, on_delete=models.CASCADE, verbose_name="الصنف")
    quantity_found = models.FloatField(verbose_name="الكمية الموجودة فعلياً")

    def save(self, *args, **kwargs):
        # تحديث "الرصيد الحالي" في المخزن الرئيسي أوتوماتيكياً عند حفظ الجرد
        self.item.quantity = self.quantity_found
        self.item.save()
        super().save(*args, **kwargs)


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
    start_date = models.DateField(verbose_name="تاريخ بداية الأسبوع (الخميس)")
    active_group = models.CharField(max_length=1, choices=GROUP_CHOICES, verbose_name="المجموعة النشطة")

    class Meta:
        verbose_name = "دوران الورديات الأسبوعي"
        verbose_name_plural = "دوران الورديات الأسبوعي"

    def __str__(self):
        return f"أسبوع {self.start_date} - {self.get_active_group_display()}"

# أضف هذا الموديل في ملف models.py
class PipeFighterExtraItem(models.Model):
    report = models.ForeignKey(PipeFighterOperations, on_delete=models.CASCADE, related_name='extra_items')
    item_name = models.CharField(max_length=100, verbose_name="اسم الصنف الإضافي")
    quantity = models.IntegerField(default=0, verbose_name="العدد / الكمية")
    

    class Meta:
        verbose_name = "صنف إضافي"
        verbose_name_plural = "أصناف إضافية للوردية"

# موديل المعدات المساعدة (لوادر، سيارات، حفارات حواجز)
class SupportEquipment(models.Model):
    name = models.CharField(max_length=100, verbose_name="اسم المعدة")
    category = models.CharField(max_length=50, choices=[('land', 'معدات برية'), ('sea', 'معدات بحرية')], verbose_name="التصنيف")

    def __str__(self):
        return self.name

# سجل حركة السولار العام (للموقع بالكامل)
# 1. موديل المعدات المعاونة (لوادر، حفارات، لانشات، مولدات)
class SupportEquipment(models.Model):
    CATEGORY_CHOICES = [
        ('marine', 'معدات بحرية (تتبع الكراكة/المالتي كات)'),
        ('project', 'معدات برية (تتبع موقع الإدارة والحواجز)')
    ]
    name = models.CharField(max_length=100, verbose_name="اسم المعدة")
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, verbose_name="تصنيف المعدة")

    def __str__(self):
        return f"{self.name} - ({self.get_category_display()})"

    class Meta:
        verbose_name = "معدة مساعدة"
        verbose_name_plural = "المعدات المساعدة (الأسطول)"

# 2. سجل حركة السولار العام (ميزان الموقع)
class FuelMovement(models.Model):
    MOVE_TYPE = [
        ('in', 'وارد للموقع (من المورد)'),
        ('out', 'منصرف لمعدة (استهلاك)')
    ]

    # تحديد المصادر والوجهات بدقة كما شرحت لي
    SOURCE_CHOICES = [
        ('truck', 'عربية السولار (المورد الخارجي)'),
        ('multicat_tank', 'عهدة المالتي كات (الفنطاس)'),
        ('admin_tank', 'خزان الموقع الإداري (التانك الأرضي)')
    ]

    date = models.DateTimeField(default=timezone.now, verbose_name="التاريخ والوقت")
    move_type = models.CharField(max_length=5, choices=MOVE_TYPE, verbose_name="نوع الحركة")
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, verbose_name="مصدر السولار")

    # لمن نرسل السولار؟ (إما كراكة، أو معدة مساعدة)
    destination_dredger = models.ForeignKey('Dredger', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الجهة المستلمة: كراكة")
    destination_equipment = models.ForeignKey(SupportEquipment, on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الجهة المستلمة: معدة أخرى")

    amount = models.FloatField(verbose_name="الكمية (لتر)")
    notes = models.CharField(max_length=255, blank=True, verbose_name="ملاحظات (رقم بون / اسم السائق)")

    def __str__(self):
        return f"{self.date.date()} | {self.get_move_type_display()} | {self.amount} لتر"

    class Meta:
        verbose_name = "حركة سولار"
        verbose_name_plural = "سجل حركات السولار (الميزان)"
# أضف هذا في core/models.py

# 1. جدول الأقسام (تنشئه من الأدمين براحتك)
class InventoryCategory(models.Model):
    name = models.CharField(max_length=100, verbose_name="اسم القسم")
    
    def __str__(self):
        return self.name
    class Meta: verbose_name = "قسم مخزني"; verbose_name_plural = "الأقسام"

# 2. جدول الأصناف (الأساسي)
class InventoryItem(models.Model):
    category = models.ForeignKey(InventoryCategory, on_delete=models.CASCADE, related_name='items', verbose_name="القسم")
    name = models.CharField(max_length=100, verbose_name="اسم الصنف")
    quantity = models.FloatField(default=0, verbose_name="الرصيد الحالي")

    def __str__(self):
        return f"{self.name} ({self.category.name})"

# 1. مخزن البر (الموقع) - ثابت للأرصدة
class InventoryItem(models.Model):
    # الخيارات الجديدة للتوزيع
    ASSIGNMENT_CHOICES = [
        ('site', 'مخزن البر (الموقع)'),
        ('marine', 'جرد الكراكة (البحرية)'),
        ('pipe', 'تقرير الخط (البايب فيتر)'),
        ('all', 'يظهر في جميع الأقسام'),
    ]

    name = models.CharField(max_length=100, verbose_name="اسم الصنف")
    # هنخلي القسم "نص" عشان تكتب اللي إنت عايزه (إضافة قسم يدوي)
    category = models.CharField(max_length=100, verbose_name="القسم (مثلاً: حبال، مواسير، عدد)")
    # الحقل الجديد للتوزيع
    assign_to = models.CharField(max_length=10, choices=ASSIGNMENT_CHOICES, default='site', verbose_name="مكان الظهور")
    quantity = models.FloatField(default=0, verbose_name="الرصيد الحالي")

    def __str__(self):
        return f"{self.name} - {self.category}"


class MarineInventoryReport(models.Model):
    # السطرين دول أهم حاجة للفصل
    REPORT_TYPES = [('marine', 'جرد كراكة'), ('site', 'جرد موقع')]
    report_type = models.CharField(max_length=10, choices=REPORT_TYPES, default='marine', verbose_name="نوع الجرد")
    
    date = models.DateTimeField(auto_now_add=True)
    operator = models.ForeignKey('Staff', on_delete=models.CASCADE)
    notes = models.TextField(blank=True, null=True)


class MarineInventoryDetail(models.Model):
    report = models.ForeignKey(MarineInventoryReport, on_delete=models.CASCADE, related_name='details')
    # لاحظ هنا: حولنا الصنف لنص (CharField) عشان نفصله عن مخزن البر
    item_name = models.CharField(max_length=100, verbose_name="اسم الصنف")
    category = models.CharField(max_length=100, verbose_name="القسم")
    quantity_found = models.FloatField(default=0, verbose_name="الكمية الموجودة")

class InventoryTransaction(models.Model):
    item = models.ForeignKey('InventoryItem', on_delete=models.CASCADE)
    quantity = models.FloatField()
    type = models.CharField(max_length=20) # وارد، مستخدم، هالك
    date = models.DateTimeField(auto_now_add=True)
    notes = models.CharField(max_length=255, blank=True)
    