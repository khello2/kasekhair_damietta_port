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
    dredger = models.ForeignKey('Dredger', on_delete=models.SET_NULL, null=True, blank=True)
    dredger = models.ForeignKey('Dredger', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الكراكة المعين عليها")

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
    show_quantity_in_report = models.BooleanField(default=True, verbose_name="إظهار إجمالي المكعبات في التقرير المطبوع")

    # 🔒 حقول الصب الثابتة المعتمدة (تُلقم عند الإغلاق لمنع تكرار الحسابات)
    frozen_total_m3 = models.FloatField(default=0.0, verbose_name="إجمالي المكعبات المجمدة")
    frozen_total_meters = models.FloatField(default=0.0, verbose_name="إجمالي الأمتار المجمدة")
    frozen_work_hours = models.CharField(max_length=10, default="00:00", verbose_name="ساعات التشغيل المجمدة")
    frozen_stop_hours = models.CharField(max_length=10, default="00:00", verbose_name="ساعات التوقف المجمدة")
    frozen_fuel_usage = models.FloatField(default=0.0, verbose_name="استهلاك السولار المجمد")
    frozen_main_net = models.CharField(max_length=10, default="00:00", verbose_name="صافي ساعات الرئيسي المجمد")
    frozen_aux_net = models.CharField(max_length=10, default="00:00", verbose_name="صافي ساعات المساعد المجمد")

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
        ('breakdown_hydrulic','عطل هيدروليك'),
        ('welding', 'أعمال لحام'),
        ('maintenance', 'صيانة دورية / عمرة'),
        ('anchors', 'نقل مخاطيف'),
        ('maneuver', 'تشفيت / تغيير موقع'),
        ('pipeline_washed', 'غسيل خط/ضخ مياه'),
        ('pipeline', 'فك / تركيب / إصلاح خط الطرد'),
        ('weather', 'توقف بسبب سوء الأحوال الجوية'),
        ('waiting_barge', 'انتظار صندل / تموين'),
        ('safety', 'توقف لأسباب تتعلق بالسلامة'),
        ('inspection', 'تفتيش / زيارة رسمية'),
        ('handover', 'استلام وتسليم وردية'),
        ('shift_end', 'نهاية وردية ( 12 ساعة)'),
        ('obstruction', 'عوائق بالتربة'),
        ('stone_box', 'فتح صندوق الحجارة'),
        ('cutter_check', 'التشييك على الكتر'),
        ('pipe_change', 'تغيير ماسورة بالخط'),
        ('rubber_change', 'تغيير رابر بالخط'),
        ('other', 'توقف لأسباب أخرى'),
    ]


    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='other', verbose_name="الحالة")
    # ... باقي الحقول كما هي ...

    def clean(self):
        super().clean()
        
        # 🎯 حارس التطهير الصامت: لو الوردية دي مش تسليم عهدة صريح، والملاحظات عهدة معلقة،
        # نطهر الملاحظات فوراً لكسر الدائرة المعلقة بره، مع الحفاظ الكامل على الحالة المورثة بدون تغيير
        if self.status != 'handover' and self.stop_reason == "عهدة معلقة بانتظار الاستلام":
            self.stop_reason = ""
        
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

    # 🧱 2. حقول الربط الأساسية والتواريخ
    report_24h = models.ForeignKey('DailyProjectReport', on_delete=models.CASCADE, related_name='shifts', null=True, blank=True, verbose_name="اليوم المرتبط")
    operator = models.ForeignKey('Staff', on_delete=models.SET_NULL, null=True, verbose_name="المشغل")
    shift_time = models.CharField(max_length=10, choices=SHIFT_TYPE, verbose_name="فترة الوردية", null=True, blank=True)

    start_time = models.DateTimeField(default=timezone.now, verbose_name="وقت الاستلام/البدء")
    end_time = models.DateTimeField(null=True, blank=True, verbose_name="وقت التسليم/التوقف")

    # 📍 3. حقول الإحداثيات والخطوط المرنة
    start_east = models.FloatField(null=True, blank=True, verbose_name="E البداية")
    start_north = models.FloatField(null=True, blank=True, verbose_name="N البداية")
    end_east = models.FloatField(null=True, blank=True, verbose_name="E النهاية")
    end_north = models.FloatField(null=True, blank=True, verbose_name="N النهاية")

    quantity_m3 = models.FloatField(default=0, verbose_name="الكمية المكعبة")
    progress_meters = models.FloatField(null=True, blank=True, verbose_name="أمتار التقدم (من الخريطة)")
    depth = models.FloatField(default=0, verbose_name="العمق")

    floating_line = models.FloatField(default=0, verbose_name="طول الخط العائم (م)")
    land_line = models.FloatField(default=0, verbose_name="طول الخط الأرضي (م)")

    @property
    def total_line_length(self):
        return (self.floating_line or 0) + (self.land_line or 0)

    # ⚠️ 4. الأعطال والصور
    stop_reason = models.TextField(null=True, blank=True, verbose_name="سبب التوقف")
    stop_image = models.ImageField(upload_to='stops/%Y/%m/', null=True, blank=True, verbose_name="صورة التوقف")

    # ⚙️ 5. ساعات الماكينات وحساب مدد حرق الديزل
    main_engine_hours = models.FloatField(default=0, verbose_name="sاعات الماكينة الرئيسية")
    aux_engine_hours = models.FloatField(default=0, verbose_name="ساعات الماكينة المساعدة")
    fuel_usage = models.FloatField(default=0, verbose_name="السولار المستهلك")

    fuel_start = models.FloatField(default=0, verbose_name="كمية السولار بداية الوردية (لتر)")
    fuel_end = models.FloatField(default=0, verbose_name="كمية السولار نهاية الوردية (لتر)")
    fuel_received = models.FloatField(default=0, verbose_name="السولار المستلم/تموين (لتر)")
    
    # ⛽ حقول الخصم والتحويل الثلاثية لضبط ميزان السولار المنقول لشيفت B
    fuel_to_dredger = models.FloatField(default=0.0, verbose_name="سولار منقول لكراكة أخرى (لتر)")
    fuel_to_excavator = models.FloatField(default=0.0, verbose_name="سولار منقول لحفار خدمة (لتر)")
    fuel_to_multicat = models.FloatField(default=0.0, verbose_name="سولار منقول لمعدة بحرية/مالتي كات (لتر)")

    main_engine_start = models.FloatField(default=0, verbose_name="ساعة الماكينة الرئيسية (بداية)")
    main_engine_end = models.FloatField(default=0, verbose_name="ساعة الماكينة الرئيسية (نهاية)")

    aux_engine_start = models.FloatField(default=0, verbose_name="ساعة الماكينة المساعدة (بداية)")
    aux_engine_end = models.FloatField(default=0, verbose_name="ساعة الماكينة المساعدة (نهاية)")

    # 📏 6. الصبة الخرسانية الكبرى: تطهير حقول الأعماق والسوينج تماماً من الـ default لمنع التعليق
    depth_before = models.FloatField(null=True, blank=True, verbose_name="العمق قبل التكريك (م)")
    depth_after = models.FloatField(null=True, blank=True, verbose_name="العمق بعد التكريك (م)")
    swing_width = models.FloatField(null=True, blank=True, verbose_name="عرض السوينج (م)")

    class Meta:
        verbose_name = "سجل وردية"
        verbose_name_plural = "سجلات الورديات (Live)"

    def __str__(self):
        return f"{self.operator if self.operator else 'بدون اسم'} - {self.start_time.strftime('%Y-%m-%d %H:%M')}"

    # 💎 محرك التوريث التلقائي الآمن: توريث الأعماق والسوينج فقط، وتصفير أمتار التقدم منعا للخطأ البشري
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # الفحص: لو السجل ده لسه جديد تماماً ومفتوحش في قاعدة البيانات
        if not self.pk:
            try:
                # جلب آخر سجل وردية مسجل تاريخياً في قاعدة البيانات بالكامل للكراكة
                last_recorded = WorkShift.objects.filter(
                    depth_before__isnull=False
                ).order_by('-id').first()

                if last_recorded:
                    # 🧬 توريث جينات الأعماق والسوينج الثابتة تلقائياً في الخانات
                    if self.depth_before is None or self.depth_before == 0.0:
                        self.depth_before = last_recorded.depth_before
                    if self.depth_after is None or self.depth_after == 0.0:
                        self.depth_after = last_recorded.depth_after
                    if self.swing_width is None or self.swing_width == 0.0:
                        self.swing_width = last_recorded.swing_width
                
                # 🚫 الإجبار الأمني عافية: تصفير أمتار التقدم لكي يكتبها المشغل بنفسه في البحر
                self.progress_meters = 0.0
            except Exception:
                # حماية هيدروليكية صامتة منعاً للكراش
                pass

    def save(self, *args, **kwargs):
        # 1. ⚙️ محرك حساب ساعات تشغيل المحركات (رئيسي ومساعد) الفعلي
        if self.main_engine_end and self.main_engine_start and float(self.main_engine_end) > 0:
            self.main_engine_hours = max(0.0, float(self.main_engine_end) - float(self.main_engine_start))
        else:
            self.main_engine_hours = 0.0

        if self.aux_engine_end and self.aux_engine_start and float(self.aux_engine_end) > 0:
            self.aux_engine_hours = max(0.0, float(self.aux_engine_end) - float(self.aux_engine_start))
        else:
            self.aux_engine_hours = 0.0

        # 2. ⛽ ميزان السولار المطور والمعدل لرفع الظلم عن شيفت B
        # الحساب بيتم فقط لو دخلنا "سولار نهاية الوردية" أكبر من الصفر
        if self.fuel_end and float(self.fuel_end) > 0:
            total_available = float(self.fuel_start or 0.0) + float(self.fuel_received or 0.0)
            
            # تجميع الـ 3 خيارات بتوع السولار المنقول بره تانك الكراكة
            total_transferred = (
                float(getattr(self, 'fuel_to_dredger', 0.0) or 0.0) + 
                float(getattr(self, 'fuel_to_excavator', 0.0) or 0.0) + 
                float(getattr(self, 'fuel_to_multicat', 0.0) or 0.0)
            )
            
            # الاستهلاك الصافي لحرق الماكينات = المتاح - النهاية - إجمالي المنقول الثلاثي
            self.fuel_usage = max(0.0, total_available - float(self.fuel_end) - total_transferred)
        else:
            self.fuel_usage = 0.0

        # 📏 الحساب الهندسي الآمن للكمية بالمكعب (محمي 100% ضد الفراغ في الأدمن بانل)
        if hasattr(self, 'depth_after') and hasattr(self, 'depth_before') and self.depth_after is not None and self.depth_before is not None:
            try:
                # الفحص: لو الخانات مسجلة صفر أو فاضية تماماً، يتخطى الحسبة وينزلها صفر صامت
                d_after = float(self.depth_after)
                d_before = float(self.depth_before)
                progress = float(self.progress_meters or 0.0)
                swing = float(self.swing_width or 0.0)
                
                if d_after > 0.0 and d_before > 0.0 and progress > 0.0:
                    depth_diff = abs(d_after - d_before)
                    self.quantity_m3 = round(depth_diff * progress * swing, 2)
                else:
                    self.quantity_m3 = 0.0
            except (ValueError, TypeError):
                self.quantity_m3 = 0.0
        else:
            self.quantity_m3 = 0.0

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

    # 4. المهمات والأدوات والعدد (تأكد من وجود الـ 10 حقول كاملة هنا)
    bolts_30 = models.IntegerField(default=0, verbose_name="مسامير 30مم")
    bolts_27 = models.IntegerField(default=0, verbose_name="مسامير 27مم")
    bolts_24 = models.IntegerField(default=0, verbose_name="مسامير 24مم")

    wrench_30 = models.IntegerField(default=0, verbose_name="مفتاح 30")
    wrench_27 = models.IntegerField(default=0, verbose_name="مفتاح 27")
    wrench_24 = models.IntegerField(default=0, verbose_name="مفتاح 24مم")

    socket_30 = models.IntegerField(default=0, verbose_name="لقمة 30مم")
    socket_27 = models.IntegerField(default=0, verbose_name="لقمة 27مم")
    socket_24 = models.IntegerField(default=0, verbose_name="لقمة 24مم")

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
class NewsTicker(models.Model):
    message = models.CharField(max_length=500, verbose_name="التعليمات / الخبر")
    is_active = models.BooleanField(default=True, verbose_name="تفعيل")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "شريط أخبار"
        verbose_name_plural = "أشرطة الأخبار"

# 7. المخازن
# أضف هذا في core/models.py

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


# 1. جدول الأقسام (تنشئه من الأدمين براحتك)
class InventoryCategory(models.Model):
    name = models.CharField(max_length=100, verbose_name="اسم القسم")

    def __str__(self):
        return self.name
    class Meta: verbose_name = "قسم مخزني"; verbose_name_plural = "الأقسام"


class MarineInventoryReport(models.Model):
    REPORT_TYPES = [('marine', 'جرد كراكة'), ('site', 'جرد موقع')]
    report_type = models.CharField(max_length=10, choices=REPORT_TYPES, default='marine', verbose_name="نوع الجرد")

    date = models.DateTimeField(auto_now_add=True)
    operator = models.ForeignKey('Staff', on_delete=models.CASCADE)
    notes = models.TextField(blank=True, null=True)
    
    # 🏗️ السطر الفولاذي الجديد لربط محضر الجرد بالكراكة المستهدفة ومنع الـ TypeError
    dredger = models.ForeignKey('Dredger', on_delete=models.SET_NULL, null=True, blank=True, verbose_name="الكراكة")


class InventoryItem(models.Model):
    name = models.CharField(max_length=100, verbose_name="اسم الصنف")
    category = models.CharField(max_length=100, verbose_name="القسم (مثلاً: حبال، مواسير، عدد)")

    # --- خانات الاختيار المتعدد الجديدة ---
    show_in_site = models.BooleanField(default=True, verbose_name="يظهر في مخزن البر (الموقع)")
    show_in_marine = models.BooleanField(default=False, verbose_name="يظهر في جرد الكراكة (البحرية)")
    show_in_pipe = models.BooleanField(default=False, verbose_name="يظهر في تقرير الخط (البايب فيتر)")

    # الأرصدة الثلاثة المستقلة (المعزولة تماماً)
    quantity_site = models.FloatField(default=0, verbose_name="رصيد مخزن البر الحالي")
    quantity_marine = models.FloatField(default=0, verbose_name="رصيد بحرية الكراكة الحالي")
    quantity_pipe = models.FloatField(default=0, verbose_name="رصيد البايب فيتر الحالي")

    def __str__(self):
        return f"{self.name} - {self.category}"



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

    class Meta:
        verbose_name = "معاملة جرد"
        verbose_name_plural = "سجل معاملات الجرد"

class EmergencyAlert(models.Model):
    ALERT_TYPES = [
        ('pipe_rubber', '🚨 قطع رابر بخط الطرد'),
        ('pipe_crack', '🚨 شرخ ماسورة بخط الطرد'),
        ('pipe_out', '🚨 خروج الخط عن المسار'),
        ('fuel_urg', '🚨 طلب تموين سولار عاجل'),
    ]
    
    dredger = models.ForeignKey(Dredger, on_delete=models.CASCADE, related_name='alerts', verbose_name="الكراكة")
    operator = models.ForeignKey(Staff, on_delete=models.SET_NULL, null=True, verbose_name="المُبلّغ")
    alert_type = models.CharField(max_length=30, choices=ALERT_TYPES, verbose_name="نوع الطوارئ")
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="توقيت البلاغ")
    is_resolved = models.BooleanField(default=False, verbose_name="تم التعامل وحل المشكلة")

    class Meta:
        verbose_name = "بلاغ طوارئ وعطل عاجل"
        verbose_name_plural = "بلاغات الطوارئ الأعطال العاجلة"

    def __str__(self):
        return f"{self.dredger.name} - {self.get_alert_type_display()}"

class ProcurementOrder(models.Model):
    STATUS_CHOICES = [
        ('pending', '⏳ طلب معلق (قيد الدراسة)'),
        ('purchased', '💳 تم الشراء (في الطريق للموقع)'),
        ('delivered', '✅ وصل الموقع وتم الاستلام'),
        ('cancelled', '❌ تم إلغاء الطلب'),
    ]
    
    item_name = models.CharField(max_length=255, verbose_name="اسم العنصر / القطعة المطلوب شراءها")
    quantity = models.CharField(max_length=100, verbose_name="الكمية والمواصفة الفنية")
    requested_by = models.ForeignKey('Staff', on_delete=models.SET_NULL, null=True, verbose_name="المهندس / الكابتن طالب الشراء")
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending', verbose_name="حالة التنفيذ الحالية")
    
    date_requested = models.DateField(auto_now_add=True, verbose_name="تاريخ طلب الشراء التلقائي")
    date_executed = models.DateField(null=True, blank=True, verbose_name="تاريخ تنفيذ الشراء الفعلي")
    date_delivered = models.DateField(null=True, blank=True, verbose_name="تاريخ الاستلام في الميناء")
    
    estimated_cost = models.DecimalField(max_digits=12, decimal_places=2, default=0.0, verbose_name="التكلفة التقديرية / الفعلية")
    admin_notes = models.TextField(blank=True, verbose_name="ملاحظات الإدارة والفواتير")

    class Meta:
        ordering = ['-date_requested', '-id']
        verbose_name = "طلب شراء لوجستي"
        verbose_name_plural = "خزان المشتريات والقطع"

    def __str__(self):
        return f"{self.item_name} ({self.get_status_display()})"
