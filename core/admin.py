from django.contrib import admin
from django.utils.safestring import mark_safe
from django.utils import timezone
from datetime import time, timedelta
from .models import (
    PipeFighterExtraItem, WorkShift, Staff, Dredger, DailyProjectReport, 
    WeeklyRotation, PipeFighterOperations, NewsTicker, AdminVault, InventoryItem,
    SupportEquipment, MarineInventoryDetail, MarineInventoryReport
)
from .models import ProcurementOrder
admin.site.register(ProcurementOrder)
admin.site.site_header = "شركة قاصد خير للمقاولات"
admin.site.site_title = "بوابة إدارة المشاريع"
admin.site.index_title = "لوحة التحكم والعمليات"

def is_super(request):
    return request.user.is_active and request.user.is_superuser

def safe_register(model, admin_class=None):
    try:
        if admin.site.is_registered(model):
            admin.site.unregister(model)
        if admin_class:
            admin.site.register(model, admin_class)
        else:
            admin.site.register(model)
    except Exception:
        pass

class WorkShiftAdmin(admin.ModelAdmin):
    # 🔄 تحديث عمود العرض ليقرأ الدالة العربية المحدثة بدلاً من الحقل الخام
    list_display = ('operator', 'get_dredger', 'get_status_arabic', 'fuel_usage', 'main_engine_hours')
    readonly_fields = ['fuel_usage', 'main_engine_hours', 'aux_engine_hours', 'quantity_m3']

    def has_module_permission(self, request): return True
    def has_view_permission(self, request, obj=None): return True

    def has_add_permission(self, request):
        if not request.user.is_authenticated: return False
        if is_super(request): return True
        curr = WeeklyRotation.objects.order_by('-start_date').first()
        staff = Staff.objects.filter(user=request.user).first()
        return bool(curr and staff and staff.group == curr.active_group)

    def has_change_permission(self, request, obj=None):
        if not request.user.is_authenticated: return False
        if is_super(request): return True
        if obj and obj.operator: return obj.operator.user == request.user
        return self.has_add_permission(request)

    def get_fields(self, request, obj=None):
        base = ['operator', 'status', 'start_time', 'end_time']
        engines = ['main_engine_start', 'main_engine_end', 'aux_engine_start', 'aux_engine_end']
        location = ['start_east', 'start_north', 'end_east', 'end_north']
        lines = ['floating_line', 'land_line']
        
        # 🔥 حقن الـ 3 حقول الجداد هنا بالملّي لكي تظهر فوراً في شاشة الأدمن بانل
        optional = [
            'fuel_start', 'fuel_received', 'fuel_end', 
            'fuel_to_dredger', 'fuel_to_excavator', 'fuel_to_multicat', # الثلاثي المطور للمنقول
            'progress_meters', 'depth_before', 'depth_after', 'swing_width', 'quantity_m3', 
            'stop_reason', 'stop_image'
        ]
        return base + engines + location + lines + optional


    # 🌐 محرك الترجمة الفورية لجدول الأدمن: يسحب الاسم العربي الشيك للحالة عافية ويظهره في عمود العرض
    def get_status_arabic(self, obj):
        if not obj.status:
            return "غير محدد"
        # استدعاء مترجم دجانجو الداخلي للحقول ذات الاختيارات
        return obj.get_status_display()
    get_status_arabic.short_description = 'الحالة الحالية للوردية'

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        target_fields = [
            'fuel_end', 'progress_meters', 'depth_after', 'depth_before', 'swing_width',
            'main_engine_start', 'main_engine_end', 'aux_engine_start', 'aux_engine_end'
        ]
        if db_field.name in target_fields:
            field.initial = None
        return field

    def save_model(self, request, obj, form, change):
        if not obj.fuel_end or float(obj.fuel_end) == 0:
            obj.fuel_end = obj.fuel_start
        if not obj.main_engine_end or float(obj.main_engine_end) == 0:
            obj.main_engine_end = obj.main_engine_start
        if not obj.aux_engine_end or float(obj.aux_engine_end) == 0:
            obj.aux_engine_end = obj.aux_engine_start
            
        f_start = float(obj.fuel_start or 0)
        f_rec = float(obj.fuel_received or 0)
        f_end = float(obj.fuel_end or 0)
        
        # خصم المنقول الثلاثي جوه الأدمن
        f_trans = (
            float(obj.fuel_to_dredger or 0.0) + 
            float(obj.fuel_to_excavator or 0.0) + 
            float(obj.fuel_to_multicat or 0.0)
        )
        obj.fuel_usage = max(0.0, (f_start + f_rec) - f_end - f_trans)
        
        super().save_model(request, obj, form, change)


    def get_form(self, request, obj=None, **kwargs):
        if not obj and request.user.is_authenticated:
            staff = Staff.objects.filter(user=request.user).first()
            if staff:
                prev_shift = WorkShift.objects.filter(operator=staff).order_by('-id').first()
                initial_values = {
                    'operator': staff.id,
                    'start_time': timezone.now(),
                }
                if prev_shift:
                    initial_values.update({
                        'main_engine_start': prev_shift.main_engine_end or prev_shift.main_engine_start,
                        'aux_engine_start': prev_shift.aux_engine_end or prev_shift.aux_engine_start,
                        'fuel_start': prev_shift.fuel_end or prev_shift.fuel_start,
                        'depth_before': prev_shift.depth_after or 0,
                    })
                kwargs.update({'initial': initial_values})

        form = super().get_form(request, obj, **kwargs)
        
        # 🧼 السكريبت المطور والموزون لمزامنة الحسابات لايف مع الرموز البرمجية الجديدة للنظام
        js_code = mark_safe(f"""
            <style>
                .kased-btn-group {{ width: 100%; text-align: center; padding: 15px; background: #f8f9fa; margin: 10px 0; border-radius: 8px; border: 1px solid #ddd; }}
                .kased-btn {{ background: #1a2a3a; color: #d4af37; border: 2px solid #d4af37; padding: 8px 25px; border-radius: 5px; cursor: pointer; font-weight: bold; margin: 5px; }}
                .hidden-row {{ display: none !important; }}
                .readonly-highlight {{ color: #d4af37 !important; font-weight: 900 !important; font-size: 1.3em !important; }}
            </style>
            <script>
            (function(){{
                var setup = function(){{
                    var target = document.querySelector('#workshift_form');
                    if(target && !document.querySelector('#kased_btns')){{
                        
                        var idsToClearOnly = [
                            '#id_main_engine_end', '#id_aux_engine_end',
                            '#id_fuel_end', '#id_progress_meters', 
                            '#id_depth_after', '#id_swing_width',
                            '#id_end_east', '#id_end_north'
                        ];
                        
                        var clearZeros = function() {{
                            idsToClearOnly.forEach(function(id) {{
                                var el = document.querySelector(id);
                                if (el && (el.value === '0' || el.value === '0.0' || el.value === '0.00')) {{
                                    el.value = ''; 
                                }}
                            }});
                        }};
                        
                        clearZeros();
                        setInterval(clearZeros, 1000);

                        target.addEventListener('submit', function() {{
                            var fStart = document.querySelector('#id_fuel_start');
                            var fEnd = document.querySelector('#id_fuel_end');
                            if (fStart && fEnd && fEnd.value.trim() === '') fEnd.value = fStart.value;

                            var mStart = document.querySelector('#id_main_engine_start');
                            var mEnd = document.querySelector('#id_main_engine_end');
                            if (mStart && mEnd && mEnd.value.trim() === '') mEnd.value = mStart.value;

                            var aStart = document.querySelector('#id_aux_engine_start');
                            var aEnd = document.querySelector('#id_aux_engine_end');
                            if (aStart && aEnd && aEnd.value.trim() === '') aEnd.value = aStart.value;
                            
                            var pMeters = document.querySelector('#id_progress_meters');
                            if (pMeters && pMeters.value.trim() === '') pMeters.value = '0';
                        }});

                        // ⛽ تجميع حقول الديزل والسولار مع حقن كلاسات الـ 3 حقول الجداد للمنقول هندسياً
                        var f_fuel = document.querySelectorAll('.field-fuel_start, .field-fuel_received, .field-fuel_end, .field-fuel_to_dredger, .field-fuel_to_excavator, .field-fuel_to_multicat');
                        var f_prog = document.querySelectorAll('.field-progress_meters, .field-depth_before, .field-depth_after, .field-swing_width, .field-quantity_m3');
                        var f_stop = document.querySelectorAll('.field-stop_reason, .field-stop_image');
                        
                        [...f_fuel, ...f_prog, ...f_stop].forEach(el => {{ if(el) el.classList.add('hidden-row'); }});
                        
                        var div = document.createElement('div'); div.id = 'kased_btns'; div.className = 'kased-btn-group';
                        var createBtn = (txt, rows) => {{
                            var b = document.createElement('button'); b.type = 'button'; b.className = 'kased-btn'; b.innerText = txt;
                            b.onclick = function() {{ rows.forEach(r => {{ if(r) r.classList.toggle('hidden-row'); }}); }}; return b;
                        }};
                        
                        div.appendChild(createBtn('⛽ تسجيل السولار والمنقول', f_fuel));
                        div.appendChild(createBtn('📏 تسجيل التقدم والأعماق', f_prog));
                        div.appendChild(createBtn('⚠️ وصف التوقف', f_stop));
                        target.prepend(div);
                        
                        var calc = function() {{
                            var d1 = parseFloat(document.querySelector('#id_depth_before')?.value) || 0;
                            var d2 = parseFloat(document.querySelector('#id_depth_after')?.value) || 0;
                            var p = parseFloat(document.querySelector('#id_progress_meters')?.value) || 0;
                            var s = parseFloat(document.querySelector('#id_swing_width')?.value) || 0;
                            var res = (Math.abs(d2 - d1) * p * s).toFixed(2);
                            var out = document.querySelector('.field-quantity_m3 .readonly');
                            if(out) {{ out.innerText = res + ' متر مكعب'; out.classList.add('readonly-highlight'); }}
                        }};
                        ['#id_depth_before', '#id_depth_after', '#id_progress_meters', '#id_swing_width'].forEach(id => {{
                            document.querySelector(id)?.addEventListener('input', calc);
                        }});
                    }}
                }};
                setTimeout(setup, 600);
            }})();
            </script>
        """)

        if 'operator' in form.base_fields: 
            form.base_fields['operator'].help_text = js_code
        return form


    def get_dredger(self, obj): return obj.report_24h.dredger.name if obj.report_24h else "N/A"
    get_dredger.short_description = 'الكراكة'
    
# ==========================================
# 2. إدارة عمليات الـ Pipe Fighter (الـ 8 أزرار والمخزن المؤمن)
# ==========================================
class ExtraItemInline(admin.TabularInline):
    model = PipeFighterExtraItem
    extra = 1

class PipeFighterAdmin(admin.ModelAdmin):
    list_display = ('date', 'shift', 'operator_in_charge', 'total_line_length')
    readonly_fields = ['float_length', 'land_length', 'total_line_length']
    inlines = [ExtraItemInline]

    def has_module_permission(self, request): return True
    def has_view_permission(self, request, obj=None): return True
    
    def has_add_permission(self, request): 
        if not request.user.is_authenticated: return False
        return request.user.is_superuser or Staff.objects.filter(user=request.user).exists()
        
    def has_change_permission(self, request, obj=None):
        if not request.user.is_authenticated: return False
        if request.user.is_superuser: return True
        if obj and obj.operator_in_charge: return obj.operator_in_charge.user == request.user
        return self.has_add_permission(request)

# ==========================================
# 3. إدارة المخازن والجرد (النظام المطور والمختصر للفلتر الجانبي)
# ==========================================
class InventoryItemAdmin(admin.ModelAdmin):
    list_display = (
        'name', 'category', 
        'show_in_site', 'show_in_marine', 'show_in_pipe', 
        'quantity_site', 'quantity_marine', 'quantity_pipe'
    )
    list_filter = ('category',) 
    search_fields = ('name',)

class MarineInventoryReportAdmin(admin.ModelAdmin):
    list_display = ('id', 'date', 'operator', 'report_type')
    list_filter = ('report_type', 'date')

class StaffAdmin(admin.ModelAdmin):
    list_display = ('name', 'user', 'group', 'role')

# ==========================================
# 4. منع تكرار الكروت وتخصيص جداول الكراكات والتقارير المجمعة للشركة
# ==========================================
class DredgerAdmin(admin.ModelAdmin):
    list_display = ('name',)
    def has_module_permission(self, request): return True

class DailyProjectReportAdmin(admin.ModelAdmin):
    list_display = ('dredger', 'date_started', 'show_quantity_in_report')
    list_filter = ('dredger',)
    search_fields = ('dredger__name',)
    fields = ('dredger', 'date_started', 'show_quantity_in_report')
    def has_module_permission(self, request): return True

# ==========================================
# 5. التسجيل الفولاذي الشامل والآمن لجميع الموديلات لمنع التكرار نهائياً
# ==========================================
safe_register(WorkShift, WorkShiftAdmin)
safe_register(PipeFighterOperations, PipeFighterAdmin)
safe_register(InventoryItem, InventoryItemAdmin)
safe_register(MarineInventoryReport, MarineInventoryReportAdmin)
safe_register(Staff, StaffAdmin)

safe_register(Dredger, DredgerAdmin)
safe_register(DailyProjectReport, DailyProjectReportAdmin)

safe_register(WeeklyRotation)
safe_register(NewsTicker)
safe_register(AdminVault)
safe_register(MarineInventoryDetail)
safe_register(SupportEquipment)
safe_register(ProcurementOrder)

# 🎨 محرك الحقن المركزي لتصغير وتنسيق المرشح (Filter) في جميع جداول السيستم بره وجوه
from django.contrib.admin import ModelAdmin
from django.utils.safestring import mark_safe

def patch_admin_filters():
    old_get_form = ModelAdmin.get_form
    def new_get_form(self, request, obj=None, **kwargs):
        form = old_get_form(self, request, obj, **kwargs)
        js_inject = mark_safe("""
            <style>
                #changelist-filter { width: 160px !important; font-size: 0.8rem !important; padding: 6px !important; background: #1a2a3a !important; color: #fff !important; border-radius: 8px !important; margin: 10px !important; }
                #changelist-filter h2 { font-size: 0.85rem !important; padding: 4px !important; margin: 0 0 5px 0 !important; color: #d4af37 !important; border-bottom: 1px solid #d4af37 !important; }
                #changelist-filter ul { padding-left: 4px !important; margin-right: 2px !important; }
                #changelist-filter li { padding-left: 2px !important; margin-bottom: 3px !important; }
                #changelist-filter a { color: #fff !important; font-weight: bold !important; }
                #changelist-filter a:hover, #changelist-filter .selected a { color: #d4af37 !important; }
            </style>
            <script>
                (function(){
                    var fix = function(){
                        var el = document.querySelector('#changelist-filter');
                        if(el) { el.style.width = '160px'; el.style.fontSize = '0.8rem'; }
                    };
                    fix(); setTimeout(fix, 300); setInterval(fix, 1000);
                })();
            </script>
        """)
        if hasattr(self, 'list_filter') and self.list_filter and form.base_fields:
            first_f = list(form.base_fields.keys())[0]
            if first_f in form.base_fields and not form.base_fields[first_f].help_text:
                form.base_fields[first_f].help_text = js_inject
        return form
    ModelAdmin.get_form = new_get_form

patch_admin_filters()
 
# 🔥 تسجيل جدول الطوارئ في الأدمن بانل ليظهر قدامك في لوحة التحكم فوراً
from .models import EmergencyAlert

@admin.register(EmergencyAlert)
class EmergencyAlertAdmin(admin.ModelAdmin):
    list_display = ['dredger', 'alert_type', 'operator', 'created_at', 'is_resolved']
    list_filter = ['is_resolved', 'alert_type', 'dredger']
    search_fields = ['dredger__name', 'operator__name']
