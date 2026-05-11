from django.contrib import admin
from django.utils.safestring import mark_safe
from django.utils import timezone
from datetime import time, timedelta
from .models import (
    PipeFighterExtraItem, WorkShift, Staff, Dredger, DailyProjectReport, 
    WeeklyRotation, PipeFighterOperations, NewsTicker, AdminVault, InventoryItem,
    SupportEquipment, FuelMovement, MarineInventoryDetail, MarineInventoryReport, InventoryCategory
)

# إعدادات واجهة الأدمين
admin.site.site_header = "شركة قاصد خير للمقاولات"
admin.site.site_title = "بوابة إدارة المشاريع"
admin.site.index_title = "لوحة التحكم والعمليات"

def is_super(request):
    return request.user.is_active and request.user.is_superuser

# ==========================================
# 1. إدارة ورديات الكراكة (أزرار الكراكة)
# ==========================================
@admin.register(WorkShift)
class WorkShiftAdmin(admin.ModelAdmin):
    list_display = ('operator', 'get_dredger', 'status', 'fuel_usage', 'main_engine_hours')
    readonly_fields = ['fuel_usage', 'main_engine_hours', 'aux_engine_hours', 'quantity_m3']

    def has_module_permission(self, request): return True
    def has_view_permission(self, request, obj=None): return True

    def has_add_permission(self, request):
        if is_super(request): return True
        curr = WeeklyRotation.objects.order_by('-start_date').first()
        staff = Staff.objects.filter(user=request.user).first()
        return bool(curr and staff and staff.group == curr.active_group)

    def has_change_permission(self, request, obj=None):
        if is_super(request): return True
        if obj: return obj.operator.user == request.user
        return self.has_add_permission(request)

    def get_fields(self, request, obj=None):
        base = ['operator', 'status', 'start_time', 'end_time']
        engines = ['main_engine_start', 'main_engine_end', 'aux_engine_start', 'aux_engine_end']
        location = ['start_east', 'start_north', 'end_east', 'end_north']
        lines = ['floating_line', 'land_line']
        optional = ['fuel_start', 'fuel_received', 'fuel_end', 'progress_meters', 
                    'depth_before', 'depth_after', 'swing_width', 'quantity_m3', 
                    'stop_reason', 'stop_image']
        return base + engines + location + lines + optional

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        # تحديد هل نحن في حالة "إضافة وردية جديدة" (استلام) أم تعديل وردية قائمة
        is_add = obj is None
        
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
                        
                        // 1. تحديد الحقول
                        var f_fuel = document.querySelectorAll('.field-fuel_start, .field-fuel_received, .field-fuel_end');
                        var f_prog = document.querySelectorAll('.field-progress_meters, .field-depth_before, .field-depth_after, .field-swing_width, .field-quantity_m3');
                        var f_stop = document.querySelectorAll('.field-stop_reason, .field-stop_image');
                        var f_engines = document.querySelectorAll('.field-main_engine_start, .field-main_engine_end, .field-aux_engine_start, .field-aux_engine_end');
                        var f_location = document.querySelectorAll('.field-start_east, .field-start_north, .field-end_east, .field-end_north');

                        // 2. منطق الإخفاء الأولي الذكي (حسب الحالة: استلام أم تشغيل)
                        var isAdd = {'true' if is_add else 'false'};
                        
                        // إخفاء كل الحقول الاختيارية في البداية
                        [...f_fuel, ...f_prog, ...f_stop].forEach(el => {{ if(el) el.classList.add('hidden-row'); }});

                        var div = document.createElement('div'); div.id = 'kased_btns'; div.className = 'kased-btn-group';
                        
                        var createBtn = (txt, rows) => {{
                            var b = document.createElement('button'); b.type = 'button'; b.className = 'kased-btn'; b.innerText = txt;
                            b.onclick = function() {{ rows.forEach(r => {{ if(r) r.classList.toggle('hidden-row'); }}); }};
                            return b;
                        }};

                        // إضافة الأزرار
                        div.appendChild(createBtn('⛽ تسجيل السولار', f_fuel));
                        // زر التقدم والتوقف يظهروا فقط لو المشغل بدأ يشتغل (مش وقت الاستلام الفوري)
                        div.appendChild(createBtn('📏 تسجيل التقدم والأعماق', f_prog));
                        div.appendChild(createBtn('⚠️ وصف التوقف', f_stop));
                        
                        target.prepend(div);

                        // 3. المحرك الهندسي للحساب اللحظي
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
        if 'operator' in form.base_fields: form.base_fields['operator'].help_text = js_code
        return form


    def get_dredger(self, obj): return obj.report_24h.dredger.name if obj.report_24h else "N/A"
    get_dredger.short_description = 'الكراكة'

# ==========================================
# 2. إدارة عمليات الـ Pipe Fighter (الـ 8 أزرار)
# ==========================================
class ExtraItemInline(admin.TabularInline):
    model = PipeFighterExtraItem
    extra = 1

@admin.register(PipeFighterOperations)
class PipeFighterAdmin(admin.ModelAdmin):
    list_display = ('date', 'shift', 'operator_in_charge', 'total_line_length')
    readonly_fields = ['float_length', 'land_length', 'total_line_length']
    inlines = [ExtraItemInline]

    def has_module_permission(self, request): return True
    def has_view_permission(self, request, obj=None): return True
    
    def has_add_permission(self, request):
        return request.user.is_superuser or Staff.objects.filter(user=request.user).exists()
    
    def has_change_permission(self, request, obj=None):
        if request.user.is_superuser: return True
        if obj and obj.operator_in_charge: return obj.operator_in_charge.user == request.user
        return self.has_add_permission(request)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        js_code = mark_safe("""
            <style>
                .pf-btn-group { display: grid; grid-template-columns: repeat(2, 1fr); gap: 10px; background: #f8f9fa; padding: 15px; border: 1px solid #d4af37; border-radius: 10px; margin-bottom: 20px; }
                .pf-btn { background: #1a2a3a; color: #d4af37; font-weight: bold; padding: 10px; border: 2px solid #d4af37; cursor: pointer; border-radius: 5px; transition: 0.3s; }
                .pf-btn:hover { background: #d4af37; color: #1a2a3a; }
                .hidden-row { display: none !important; }
            </style>
            <script>
            (function(){
                var setup = function(){
                    var target = document.querySelector('#pipefighteroperations_form');
                    var extraInline = document.querySelector('.inline-group'); 
                    if(target && !document.querySelector('#pf_btns')){
                        var groups = {
                            'f1': document.querySelectorAll('.field-float_pipes, .field-float_rubbers, .field-float_pontoons, .field-float_pantons, .field-float_anchors'),
                            'f2': document.querySelectorAll('.field-land_pipes, .field-land_rubbers'),
                            'f3': document.querySelectorAll('.field-stock_pipes_new, .field-stock_pipes_used, .field-stock_pipes_scrap'),
                            'f4': document.querySelectorAll('.field-stock_rubbers_new, .field-stock_rubbers_used, .field-stock_rubbers_scrap'),
                            'f5': document.querySelectorAll('.field-stock_pontoons_new, .field-stock_pontoons_used, .field-stock_pontoons_scrap'),
                            'f6': document.querySelectorAll('.field-bolts_30, .field-bolts_27, .field-wrench_30, .field-wrench_27, .field-socket_30, .field-socket_27, .field-air_gun'),
                            'f8': document.querySelectorAll('.field-work_description, .field-work_photos')
                        };
                        Object.values(groups).flat().forEach(el => { if(el) el.classList.add('hidden-row'); });
                        if(extraInline) extraInline.classList.add('hidden-row');

                        var div = document.createElement('div'); div.id = 'pf_btns'; div.className = 'pf-btn-group';
                        var createBtn = (txt, rows, isInline=false) => {
                            var b = document.createElement('button'); b.type = 'button'; b.className = 'pf-btn'; b.innerText = txt;
                            b.onclick = function() {
                                if(isInline && extraInline) extraInline.classList.toggle('hidden-row');
                                if(rows) rows.forEach(r => { if(r) r.classList.toggle('hidden-row'); });
                            }; return b;
                        };
                        div.appendChild(createBtn('1- الخط العائم', groups.f1));
                        div.appendChild(createBtn('2- الخط الأرضي', groups.f2));
                        div.appendChild(createBtn('3- استوك المواسير', groups.f3));
                        div.appendChild(createBtn('4- استوك الربرات', groups.f4));
                        div.appendChild(createBtn('5- استوك الطوافات', groups.f5));
                        div.appendChild(createBtn('6- المهمات والأدوات', groups.f6));
                        div.appendChild(createBtn('7- إضافة أصناف أخرى', null, true));
                        div.appendChild(createBtn('8- بيان أعمال الوردية', groups.f8));
                        target.prepend(div);
                    }
                }; setTimeout(setup, 600);
            })();
            </script>
        """)
        if 'operator_in_charge' in form.base_fields: form.base_fields['operator_in_charge'].help_text = js_code
        return form

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)
        last_report = PipeFighterOperations.objects.order_by('-date', '-id').first()
        
        if last_report:
            # 1. الخط بالخدمة
            initial['float_pipes'] = last_report.float_pipes
            initial['float_rubbers'] = last_report.float_rubbers
            initial['float_pontoons'] = last_report.float_pontoons
            initial['float_pantons'] = last_report.float_pantons
            initial['float_anchors'] = last_report.float_anchors
            initial['land_pipes'] = last_report.land_pipes
            initial['land_rubbers'] = last_report.land_rubbers
            
            # 2. استوك المواسير
            initial['stock_pipes_new'] = last_report.stock_pipes_new
            initial['stock_pipes_used'] = last_report.stock_pipes_used
            initial['stock_pipes_scrap'] = last_report.stock_pipes_scrap
            
            # 3. استوك الربرات (المضافة حديثاً)
            initial['stock_rubbers_new'] = last_report.stock_rubbers_new
            initial['stock_rubbers_used'] = last_report.stock_rubbers_used
            initial['stock_rubbers_scrap'] = last_report.stock_rubbers_scrap
            
            # 4. استوك الطوافات
            initial['stock_pontoons_new'] = last_report.stock_pontoons_new
            initial['stock_pontoons_used'] = last_report.stock_pontoons_used
            initial['stock_pontoons_scrap'] = last_report.stock_pontoons_scrap
            
            # 5. المهمات والأدوات
            initial['bolts_30'] = last_report.bolts_30
            initial['bolts_27'] = last_report.bolts_27
            initial['wrench_30'] = last_report.wrench_30
            initial['wrench_27'] = last_report.wrench_27
            initial['socket_30'] = last_report.socket_30
            initial['socket_27'] = last_report.socket_27
            initial['air_gun'] = last_report.air_gun
            
        return initial

# ==========================================
# 3. تسجيل باقي الموديلات
# ==========================================
@admin.register(SupportEquipment)
class SupportEquipmentAdmin(admin.ModelAdmin):
    list_display = ('name', 'category')

@admin.register(FuelMovement)
class FuelMovementAdmin(admin.ModelAdmin):
    list_display = ('date', 'move_type', 'source', 'amount')

@admin.register(Staff)
class StaffAdmin(admin.ModelAdmin):
    list_display = ('name', 'group', 'team_type')

@admin.register(InventoryItem)
class InventoryAdmin(admin.ModelAdmin):
    list_display = ('name', 'quantity')

admin.site.register(Dredger)
admin.site.register(DailyProjectReport)
admin.site.register(WeeklyRotation)
admin.site.register(NewsTicker)
admin.site.register(AdminVault)

class MarineInventoryDetailInline(admin.TabularInline):
    model = MarineInventoryDetail
    fields = ('item_name', 'category', 'quantity_found')
    extra = 0 

# في core/admin.py (نسخة مؤقتة للتجربة)
class MarineInventoryDetailInline(admin.TabularInline):
    model = MarineInventoryDetail
    fields = ('item_name', 'category', 'quantity_found')
    extra = 0 

@admin.register(MarineInventoryReport)
class MarineInventoryReportAdmin(admin.ModelAdmin):
    list_display = ('date', 'operator')
    inlines = [MarineInventoryDetailInline]
