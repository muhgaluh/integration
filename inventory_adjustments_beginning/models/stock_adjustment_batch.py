# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
import logging

_logger = logging.getLogger(__name__)

class StockOpeningBatch(models.Model):
    _name = 'stock.opening.batch'
    _description = 'Opening Balance Batch'
    _order = 'id desc'

    name = fields.Char(string='Reference', required=True, copy=False, readonly=True, states={'draft': [('readonly', False)]}, default=lambda self: _('New'))
    user_id = fields.Many2one('res.users', string='Responsible', default=lambda self: self.env.user, readonly=True)
    date = fields.Datetime(string='Date', default=fields.Datetime.now)
    reason = fields.Text(string='Reason')
    state = fields.Selection([('draft', 'Draft'),('in_progress', 'In Progress'),('done', 'Done'),('cancel', 'Cancelled')], string='Status', default='draft', readonly=True, copy=False)

    line_ids = fields.One2many('stock.opening.batch.line', 'batch_id', string='Adjustments')
    is_stock_manager = fields.Boolean(compute='_compute_is_stock_manager')
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id, required=True)

    # --- HEADER FIELDS ---
    journal_entry_id = fields.Many2one(
        'account.move',
        string='Source Journal Entry',
        domain="[('state', '=', 'posted'), ('move_type', '=', 'entry')]",
        help="Pilih Jurnal Manual (MISC) yang berisi saldo awal.",
        required=True
    )
    
    manual_journal_ref = fields.Char(
        string='Reference Override',
        help="Referensi yang akan ditempel ke Jurnal Stok."
    )

    # --- SUMMARY / RECONCILIATION TAB ---
    summary_ids = fields.One2many('stock.opening.summary', 'batch_id', string='Reconciliation Summary')
    
    # --- TOTALS (LOGIC BARU) ---
    # 1. Total Fisik (Semua)
    total_inventory_value = fields.Monetary(string="Total Inventory", compute='_compute_batch_totals', currency_field='currency_id')
    
    # 2. Total Target (Hanya yang Dicentang)
    total_active_target = fields.Monetary(
        string="Target (Selected)", 
        compute='_compute_active_totals', 
        currency_field='currency_id',
        store=True,     # WAJIB: Agar tersimpan di database
        readonly=True   # WAJIB: Agar dipaksa hitung otomatis oleh Odoo
    )
    
    total_active_variance = fields.Monetary(
        string="Variance (Selected)", 
        compute='_compute_active_totals', 
        currency_field='currency_id',
        store=True,     # WAJIB
        readonly=True   # WAJIB
    )

    # --- STATUS REKONSILIASI ---
    reconciliation_status = fields.Selection([
        ('empty', 'Not Calculated'),
        ('unbalanced', 'Unbalanced'),
        ('balanced', 'Matched')
    ], string='Reconciliation Status', compute='_compute_reconciliation_status', store=True)

    @api.depends('summary_ids', 'summary_ids.variance', 'summary_ids.to_override')
    def _compute_reconciliation_status(self):
        for batch in self:
            if not batch.summary_ids:
                batch.reconciliation_status = 'empty'
            else:
                relevant_summaries = batch.summary_ids.filtered(lambda s: s.to_override)
                # Gunakan toleransi float (misal 1.0)
                has_variance = any(abs(s.variance) > 1.0 for s in relevant_summaries)
                
                if has_variance:
                    batch.reconciliation_status = 'unbalanced'
                else:
                    batch.reconciliation_status = 'balanced'
    
    @api.depends('summary_ids.to_override', 'summary_ids.journal_value', 'summary_ids.variance')
    def _compute_active_totals(self):
        for batch in self:
            # === LOG DEBUG ===
            _logger.info(f"[DEBUG] Menghitung Total Active untuk Batch {batch.id} ({batch.name})")
            
            # Ambil hanya baris summary yang dicentang
            active_rows = batch.summary_ids.filtered(lambda s: s.to_override)
            
            total_target = sum(active_rows.mapped('journal_value'))
            total_variance = sum(active_rows.mapped('variance'))
            
            # === LOG DEBUG HASIL ===
            _logger.info(f"[DEBUG] Batch {batch.id}: Ditemukan {len(active_rows)} baris dicentang.")
            _logger.info(f"[DEBUG] Batch {batch.id}: Total Target = {total_target}, Total Variance = {total_variance}")

            # Hitung total
            batch.total_active_target = total_target
            batch.total_active_variance = total_variance

    @api.depends('line_ids.inventory_value')
    def _compute_batch_totals(self):
        for batch in self:
            batch.total_inventory_value = sum(batch.line_ids.mapped('inventory_value'))

    @api.onchange('journal_entry_id')
    def _onchange_journal_entry(self):
        if self.journal_entry_id and not self.manual_journal_ref:
            self.manual_journal_ref = self.journal_entry_id.name

    def _compute_is_stock_manager(self):
        for batch in self:
            batch.is_stock_manager = self.env.user.has_group('stock.group_stock_manager')

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('New')) == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('stock.adjustment.batch') or _('New')
        return super().create(vals_list)

    def action_request_approval(self): self.write({'state': 'in_progress'})
    
    def action_clear_lines(self): 
        self.ensure_one()
        if self.state != 'draft': raise UserError(_("Only in Draft."))
        self.line_ids.unlink()
        self.summary_ids.unlink()

    def action_set_counts_to_zero(self):
        self.ensure_one()
        if self.state != 'draft': raise UserError(_("Only in Draft."))
        if self.line_ids: self.line_ids.write({'counted_qty': 0})

    # =========================================================
    # ACTION MANUAL: HITUNG ULANG TOTAL
    # =========================================================
    def action_recalculate_totals(self):
        """Memaksa perhitungan ulang field computed store=True"""
        _logger.info(">>> TOMBOL HITUNG ULANG DITEKAN <<<")
        for batch in self:
            _logger.info(f">>> Memproses Batch {batch.name} <<<")
            batch._compute_active_totals()
            batch._compute_batch_totals()
            batch._compute_reconciliation_status()
        return True

    # =========================================================
    # LOGIC 1: SUMMARY ENGINE (PERSIST SETTINGS)
    # =========================================================
    def action_refresh_summary(self):
        self.ensure_one()
        _logger.info(">>> REFRESH SUMMARY & DATA BARU DIBUAT <<<")
        
        # 1. BACKUP SETTINGAN LAMA
        existing_settings = {s.account_id.id: s.to_override for s in self.summary_ids}
        
        # 2. Hapus Data Lama
        self.summary_ids.unlink()
        
        if not self.journal_entry_id:
            return

        summary_vals = []
        
        # 3. Hitung Ulang Data
        inventory_data = {}
        for line in self.line_ids:
            acc_id = line.contra_account_id.id
            if acc_id not in inventory_data: inventory_data[acc_id] = 0.0
            inventory_data[acc_id] += line.inventory_value

        journal_data = {}
        for move_line in self.journal_entry_id.line_ids:
            val = move_line.debit or abs(move_line.balance) 
            if val > 0:
                acc_id = move_line.account_id.id
                if acc_id not in journal_data: journal_data[acc_id] = 0.0
                journal_data[acc_id] += val

        all_accounts = set(inventory_data.keys()) | set(journal_data.keys())

        # 4. Create Summary Lines (RESTORE SETTINGAN)
        for acc_id in all_accounts:
            inv_val = inventory_data.get(acc_id, 0.0)
            jour_val = journal_data.get(acc_id, 0.0)
            
            should_override = existing_settings.get(acc_id, True)
            
            if inv_val != 0 or jour_val != 0:
                summary_vals.append({
                    'batch_id': self.id,
                    'account_id': acc_id,
                    'inventory_value': inv_val,
                    'journal_value': jour_val,
                    'variance': inv_val - jour_val,
                    'to_override': should_override 
                })
        
        self.env['stock.opening.summary'].create(summary_vals)


    # =========================================================
    # LOGIC 2: ACTION VALIDATE
    # =========================================================
    def action_validate(self):
        """
        VALIDASI FINAL (VERSION: CUSTOM LOCATION & PICKING NAME)
        - Membuat/Mencari Lokasi 'Opening Balance' (Usage: Supplier).
        - Memberi nama Picking sesuai Header Batch.
        - Supply Lot & Back-filling.
        - Force Dates via SQL.
        """
        self.ensure_one()

        # 1. SECURITY & PRE-CHECK
        if not self.env.user.has_group('inventory_adjustments_beginning.group_opening_batch_manager'):
            raise UserError("Akses Ditolak! Anda bukan Manager Opening Batch.")

        # 2. DATA PARAMETER HEADER
        forced_date = self.date or fields.Datetime.now()
        target_lot_name = self.reason or "Saldo Awal 1 November 2025"
        ghost_name = self.name.strip() # Nama Batch Kakak (Contoh: STOCK AWAL 1 NOV)

        # 3. MENGURUS LOKASI SUMBER (PARTNER LOCATION/OPENING BALANCE)
        # Cari dulu folder induknya (Partner Locations)
        parent_loc = self.env['stock.location'].search([('name', '=', 'Partner Locations')], limit=1)
        
        # Cari atau buat lokasi Opening Balance dengan Usage: Supplier
        opening_loc = self.env['stock.location'].sudo().search([
            ('name', '=', 'Opening Balance'),
            ('usage', '=', 'supplier'),
            ('location_id', '=', parent_loc.id if parent_loc else False)
        ], limit=1)

        if not opening_loc:
            opening_loc = self.env['stock.location'].sudo().create({
                'name': 'Opening Balance',
                'usage': 'supplier',
                'location_id': parent_loc.id if parent_loc else False,
                'company_id': self.env.company.id,
            })

        # 4. PERSIAPAN GUDANG & SETTING
        first_loc = self.line_ids[0].location_id
        warehouse = first_loc.warehouse_id or self.env['stock.warehouse'].search([('lot_stock_id', '=', first_loc.id)], limit=1)
        if not warehouse:
            warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
        
        picking_type = warehouse.in_type_id
        
        # BACKUP & PAKSA SETTING (Anti-OCA)
        original_use_existing = picking_type.use_existing_lots
        original_use_create = picking_type.use_create_lots
        picking_type.sudo().write({'use_existing_lots': True, 'use_create_lots': False})

        try:
            # 5. CREATE PICKING HEADER (DENGAN NAMA CUSTOM)
            picking = self.env['stock.picking'].create({
                'name': ghost_name, # Paksa nama Picking sesuai Header Batch
                'picking_type_id': picking_type.id,
                'location_id': opening_loc.id, # Pakai lokasi yang baru dibuat
                'location_dest_id': first_loc.id,
                'origin': self.manual_journal_ref or self.name,
                'company_id': self.env.company.id,
                'date': forced_date,
            })

            # 6. LOOP PRODUK & SUPPLY LOT
            for line in self.line_ids:
                if line.counted_qty <= 0: continue
                
                lot_id = False
                if line.product_id.tracking != 'none':
                    existing_lot = self.env['stock.lot'].sudo().search([
                        ('name', '=', target_lot_name),
                        ('product_id', '=', line.product_id.id),
                        ('company_id', '=', self.env.company.id)
                    ], limit=1)

                    if not existing_lot:
                        existing_lot = self.env['stock.lot'].sudo().create({
                            'name': target_lot_name,
                            'product_id': line.product_id.id,
                            'company_id': self.env.company.id,
                        })
                    
                    # Back-filling ke baris batch
                    line.write({'lot_id': existing_lot.id})
                    
                    # Force Birth Date Lot via SQL
                    self.env.cr.execute("UPDATE stock_lot SET create_date=%s WHERE id=%s", (forced_date, existing_lot.id))
                    lot_id = existing_lot.id

                # Create Move
                move = self.env['stock.move'].create({
                    'name': ghost_name,
                    'product_id': line.product_id.id,
                    'product_uom_qty': line.counted_qty,
                    'product_uom': line.product_id.uom_id.id,
                    'picking_id': picking.id,
                    'location_id': picking.location_id.id,
                    'location_dest_id': line.location_id.id,
                    'price_unit': line.unit_cost,
                    'company_id': self.env.company.id,
                    'date': forced_date,
                })

                # Create Move Line (Injection)
                self.env['stock.move.line'].create({
                    'move_id': move.id,
                    'picking_id': picking.id,
                    'product_id': line.product_id.id,
                    'lot_id': lot_id,
                    'qty_done': line.counted_qty,
                    'location_id': move.location_id.id,
                    'location_dest_id': move.location_dest_id.id,
                    'company_id': self.env.company.id,
                })

            # 7. VALIDASI PICKING
            picking.action_confirm()
            picking.with_context(
                force_period_date=forced_date,
                skip_lot_selection=True,
                auto_create_lot=False
            ).button_validate()

            # 8. SYNC SQL (VALUATION & ACCOUNTING)
            picking.write({'date_done': forced_date})
            for svl in picking.move_ids.stock_valuation_layer_ids:
                self.env.cr.execute("UPDATE stock_valuation_layer SET create_date=%s WHERE id=%s", (forced_date, svl.id))
                
                # Mirroring Jurnal
                move_acc = svl.account_move_id
                if move_acc:
                    if move_acc.state == 'posted': move_acc.button_draft()
                    move_acc.write({
                        'date': forced_date.date() if hasattr(forced_date, 'date') else forced_date, 
                        'name': False,
                        'ref': self.manual_journal_ref or self.name
                    })
                    for aml in move_acc.line_ids:
                        if aml.credit > 0:
                            inv_acc = aml.product_id.categ_id.property_stock_valuation_account_id
                            if self.journal_entry_id and inv_acc:
                                if self.journal_entry_id.line_ids.filtered(lambda l: l.account_id.id == inv_acc.id):
                                    aml.account_id = inv_acc.id
                    move_acc.action_post()

        finally:
            # Kembalikan setting gudang
            picking_type.sudo().write({'use_existing_lots': original_use_existing, 'use_create_lots': original_use_create})

        self.write({'state': 'done'})
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'BERHASIL TOTAL! 🎯',
                'message': f'Lokasi Khusus Terbentuk, Nama Picking Sesuai Header, & Data Rapi.',
                'type': 'success',
                'next': {
                    'type': 'ir.actions.client',
                    'tag': 'reload',
                }
            }
        }
    # ====================================================================
    # TAHAP 1: SCANNING (LOGIKA SELISIH & HARGA 0)
    # ====================================================================
    def action_scan_ghosts(self):
        """
        SCANNER CERDAS: 
        Mendeteksi produk yang History > Fisik, 
        lalu menghitung berapa banyak 'Layer Sampah (Rp 0)' yang bisa dibuang.
        """
        report_logs = ["=== LAPORAN ANALISA MIXED STOCK ===", ""]
        found_problem = False
        
        for line in self.line_ids:
            product = line.product_id
            
            # 1. Ambil Data
            phys_qty = product.qty_available          # Fisik Real (Contoh: 364)
            hist_qty = product.quantity_svl           # History Data (Contoh: 1308)
            
            # 2. Logic: Hanya jika History LEBIH BESAR dari Fisik
            if hist_qty > phys_qty:
                excess_qty = hist_qty - phys_qty # Jumlah yang harus dibuang (944)
                
                # Cari Layer Sampah (Value Rp 0)
                zero_layers = self.env['stock.valuation.layer'].search([
                    ('product_id', '=', product.id),
                    ('remaining_qty', '>', 0),
                    ('remaining_value', '=', 0), # HANYA YANG GRATISAN
                    ('company_id', '=', self.env.company.id)
                ])
                
                # Hitung total sampah yang tersedia
                total_trash_qty = sum(zero_layers.mapped('remaining_qty'))
                
                if total_trash_qty > 0:
                    found_problem = True
                    # Hitung estimasi: Kita hanya buang SEJUMLAH Excess atau SEADANYA Sampah
                    # (Kita pilih angka terkecil agar aman, jangan sampai memakan stok fisik)
                    qty_to_kill = min(excess_qty, total_trash_qty)
                    
                    report_logs.append(f"[TARGET] {product.default_code}")
                    report_logs.append(f"   > Fisik Gudang : {phys_qty}")
                    report_logs.append(f"   > Data History : {hist_qty} (Kelebihan: {excess_qty})")
                    report_logs.append(f"   > Layer Rp 0   : Tersedia {total_trash_qty} pcs")
                    report_logs.append(f"   > RENCANA      : Akan membuang {qty_to_kill} pcs dari layer Rp 0.")
                    
                    final_prediction = hist_qty - qty_to_kill
                    report_logs.append(f"   > HASIL NANTI  : History menjadi {final_prediction} (Mendekati Fisik)")
                    report_logs.append("")

        if not found_problem:
            raise UserError("DATA BERSIH!\nTidak ditemukan Layer Rp 0 yang menyebabkan selisih.")
        
        report_logs.append("=============================================")
        report_logs.append("REKOMENDASI: Klik tombol 'BASMI HANTU' untuk menjalankan operasi pemotongan.")
        
        raise UserError("\n".join(report_logs))
    
    # ====================================================================
    # TAHAP 2: EKSEKUSI (DELETE PERMANENT) - REVISED (FIX ERROR)
    # ====================================================================
    # def action_kill_ghosts(self):
    #     """
    #     Menghapus Layer yang Value-nya 0 pada produk yang bermasalah.
    #     """
    #     logs = ["=== HASIL EKSEKUSI CLEANING ===", ""]
    #     layers_to_kill = self.env['stock.valuation.layer']
        
    #     for line in self.line_ids:
    #         product = line.product_id
    #         phys_qty = product.qty_available
    #         hist_qty = product.quantity_svl
            
    #         # Hanya proses jika History berlebih
    #         if hist_qty > phys_qty:
    #             excess_qty = hist_qty - phys_qty # Target buang
                
    #             # Ambil Layer Sampah (Value 0), urutkan dari yg sisa terbanyak
    #             zero_layers = self.env['stock.valuation.layer'].search([
    #                 ('product_id', '=', product.id),
    #                 ('remaining_qty', '>', 0),
    #                 ('remaining_value', '=', 0),
    #                 ('company_id', '=', self.env.company.id)
    #             ], order='remaining_qty desc')
                
    #             removed_for_this_product = 0
                
    #             # LOOPING PEMOTONGAN
    #             for layer in zero_layers:
    #                 if excess_qty <= 0:
    #                     break 
                    
    #                 take_qty = min(layer.remaining_qty, excess_qty)
                    
    #                 # UPDATE SQL LANGSUNG
    #                 self.env.cr.execute("""
    #                     UPDATE stock_valuation_layer
    #                     SET remaining_qty = remaining_qty - %s
    #                     WHERE id = %s
    #                 """, (take_qty, layer.id))
                    
    #                 excess_qty -= take_qty
    #                 removed_for_this_product += take_qty
                    
    #                 # Tambahkan ke list recordset untuk referensi
    #                 layers_to_kill |= layer
                
    #             if removed_for_this_product > 0:
    #                 logs.append(f"[CLEANED] {product.default_code}")
    #                 logs.append(f"   - Target Buang : {hist_qty - phys_qty}")
    #                 logs.append(f"   - Berhasil Dibuang : {removed_for_this_product} pcs (Rp 0)")
    #                 logs.append(f"   - History Baru : {hist_qty - removed_for_this_product}")

    #     if not layers_to_kill:
    #         raise UserError("Tidak ada yang perlu dieksekusi.")

    #     # REFRESH DATA PRODUCT (BAGIAN YANG DIPERBAIKI)
    #     # Kita tidak panggil method compute manual, tapi kita invalidate cache-nya.
    #     products_to_refresh = layers_to_kill.mapped('product_id')
        
    #     for p in products_to_refresh:
    #         # 1. Reset Cost Standard jadi 0
    #         # (Agar saat barang baru masuk nanti, dia hitung fresh dari harga baru)
    #         if p.qty_available == 0:
    #             p.sudo().write({'standard_price': 0})
            
    #         # 2. INVALIDATE CACHE (PENTING!)
    #         # Ini memaksa Odoo membaca ulang data 'quantity_svl' dari SQL yang baru kita update
    #         # Odoo 14/15/16 menggunakan invalidate_recordset atau invalidate_cache
    #         try:
    #             if hasattr(p, 'invalidate_recordset'):
    #                 p.invalidate_recordset(['quantity_svl', 'value_svl'])
    #             else:
    #                 p.invalidate_cache(['quantity_svl', 'value_svl'])
    #         except Exception as e:
    #             # Jika masih error, skip saja, data di DB tetap sudah berubah kok
    #             _logger.warning(f"Gagal refresh cache produk {p.name}: {str(e)}")

    #     # COMMIT & REPORT
    #     self.env.cr.commit()
        
    #     logs.append("")
    #     logs.append("------------------------------------------------")
    #     logs.append(f"STATUS: SUKSES. {len(layers_to_kill)} Layer telah dipotong/dihapus.")
    #     logs.append("Data History sekarang sudah sinkron dengan Fisik.")
        
    #     raise UserError("\n".join(logs))

    def action_kill_ghosts(self):
        """
        EKSEKUSI MATI (MODE AMAN & KOMPATIBEL):
        1. Baca data pakai ORM (aman dari error kolom).
        2. Hapus layer hantu pakai SQL (Brute Force).
        3. Paksa Odoo baca ulang (Invalidate Cache).
        """
        logs = ["=== HASIL EKSEKUSI (FINAL FIX) ===", ""]
        products_affected = self.env['product.product']
        total_removed = 0
        
        for line in self.line_ids:
            product = line.product_id
            
            # 1. AMBIL DATA PAKAI ORM (JANGAN PAKAI SQL SELECT)
            # Biarkan Odoo yang menghitungkan, meskipun datanya masih salah (cache)
            phys_qty = product.qty_available
            hist_qty = product.quantity_svl  # Ini akan membaca data 'Hantu' 152 itu
            
            # 2. LOGIC: HANYA JIKA HISTORY LEBIH BESAR DARI FISIK
            if hist_qty > phys_qty:
                excess_qty = hist_qty - phys_qty
                
                # 3. CARI SEMUA LAYER SISA (SQL SEARCH)
                # Kita cari layer di database yang masih aktif
                # Urutkan dari yang terlama (FIFO)
                all_layers = self.env['stock.valuation.layer'].search([
                    ('product_id', '=', product.id),
                    ('remaining_qty', '>', 0),
                    ('company_id', '=', self.env.company.id)
                ], order='create_date asc')
                
                removed_this_product = 0
                
                for layer in all_layers:
                    if excess_qty <= 0:
                        break
                    
                    # Ambil mana yang lebih kecil: Sisa layer atau Target Buang
                    take_qty = min(layer.remaining_qty, excess_qty)
                    
                    # 4. SUNTIK MATI LAYER INI (SQL UPDATE)
                    # Kita potong Qty-nya secara paksa di database
                    self.env.cr.execute("""
                        UPDATE stock_valuation_layer
                        SET remaining_qty = remaining_qty - %s,
                            remaining_value = CASE 
                                WHEN (remaining_qty - %s) <= 0 THEN 0 
                                ELSE remaining_value * ((remaining_qty - %s) / remaining_qty)
                            END
                        WHERE id = %s
                    """, (take_qty, take_qty, take_qty, layer.id))
                    
                    excess_qty -= take_qty
                    removed_this_product += take_qty
                
                if removed_this_product > 0:
                    products_affected |= product
                    total_removed += removed_this_product
                    logs.append(f"[CLEANED] {product.default_code}")
                    logs.append(f"   - Target Buang: {hist_qty - phys_qty}")
                    logs.append(f"   - Terbuang: {removed_this_product}")

        # ------------------------------------------------------------------
        # FINALISASI: PAKSA ODOO BACA ULANG (CACHE FLUSH)
        # ------------------------------------------------------------------
        if products_affected:
            self.env.cr.commit() # Simpan dulu layer yang sudah dipotong
            
            logs.append("")
            logs.append("[SYNC] Melakukan Refresh Cache Odoo...")
            
            # Invalidate Cache: Memaksa Odoo melupakan angka 152 yang ada di memori
            # Dan membaca ulang dari SQL (yang layernya sudah kita nol-kan)
            try:
                if hasattr(products_affected, 'invalidate_recordset'):
                    products_affected.invalidate_recordset(['quantity_svl', 'value_svl'])
                else:
                    products_affected.invalidate_cache(['quantity_svl', 'value_svl'])
            except Exception as e:
                logs.append(f"[WARN] Cache refresh warning: {str(e)}")

            # Reset Standard Price jika barang habis total
            for p in products_affected:
                if p.qty_available == 0:
                    p.sudo().write({'standard_price': 0})

        self.env.cr.commit()
        
        # ------------------------------------------------------------------
        # LAPORAN
        # ------------------------------------------------------------------
        if total_removed == 0:
             return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'CLEANING GAGAL / SUDAH BERSIH',
                    'message': 'Sistem tidak menemukan selisih antara History vs Fisik.',
                    'type': 'warning',
                    'sticky': False,
                }
            }
            
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'EXTERMINATION SUKSES! 💀',
                'message': f"SUKSES BRUTE FORCE!\n"
                           f"- Produk Diperbaiki: {len(products_affected)}\n"
                           f"- Total Qty Dibuang: {total_removed:,.0f} pcs\n"
                           f"Layer sampah sudah dimusnahkan dari database.",
                'type': 'success',
                'sticky': True,
            }
        }
    
    def action_force_refresh_cache(self):
        """
        RADAR HANTU (INVESTIGASI TOTAL):
        Mencari setiap record di stock_valuation_layer yang menyebabkan angka 152.
        """
        self.env.cr.commit()
        target_code = "AT0143"
        product = self.line_ids.filtered(lambda l: target_code in l.product_id.display_name)[:1].product_id
        
        if not product:
            raise UserError("Produk target tidak ditemukan.")

        # 1. SCAN SEMUA LAYER (TANPA FILTER)
        # Kita cari SEMUA layer produk ini, termasuk yang qty-nya negatif, 
        # company-nya beda, atau datanya corrupt.
        self.env.cr.execute("""
            SELECT id, quantity, remaining_qty, value, remaining_value, company_id, create_date, description
            FROM stock_valuation_layer 
            WHERE product_id = %s
        """, (product.id,))
        layers = self.env.cr.dictfetchall()

        logs = [f"=== HASIL RADAR PRODUK {target_code} ==="]
        total_remaining_qty = 0
        
        for l in layers:
            total_remaining_qty += l['remaining_qty']
            logs.append(f"ID: {l['id']} | Rem Qty: {l['remaining_qty']} | Val: {l['remaining_value']} | Co: {l['company_id']} | Desc: {l['description'][:20]}")

        logs.append(f"\nTOTAL REMAINING QTY DI SQL: {total_remaining_qty}")
        
        # 2. BANDINGKAN DENGAN FISIK (QUANT)
        self.env.cr.execute("SELECT sum(quantity) FROM stock_quant WHERE product_id = %s AND location_id IN (SELECT id FROM stock_location WHERE usage='internal')", (product.id,))
        quant_qty = self.env.cr.fetchone()[0] or 0.0
        logs.append(f"TOTAL FISIK DI QUANT: {quant_qty}")

        # 3. KESIMPULAN OTOMATIS
        if total_remaining_qty != 0:
            logs.append("\nKESIMPULAN: HANTU DITEMUKAN!")
            logs.append(f"Ada {len(layers)} layer yang masih memiliki 'remaining_qty'.")
            logs.append("Kita harus membuang layer-layer ini sekarang.")
        else:
            logs.append("\nKESIMPULAN: SQL SUDAH BERSIH.")
            logs.append("Jika Odoo masih bilang 152, maka ini adalah cache level rendah.")

        raise UserError("\n".join(logs))
    def action_simulasi_nilai_final(self):
        """
        SIMULASI UNTUK MENGUJI ASUMSI:
        Apakah angka 152 akan ikut menghitung atau tidak?
        """
        self.ensure_one()
        target_code = "AT0143"
        line = self.line_ids.filtered(lambda l: target_code in l.product_id.display_name)[:1]
        
        if not line:
            raise UserError(f"Produk {target_code} tidak ada di batch ini.")

        # 1. AMBIL DATA DARI SQL (KEBENARAN DATABASE)
        self.env.cr.execute("""
            SELECT COALESCE(SUM(remaining_qty),0), COALESCE(SUM(remaining_value),0)
            FROM stock_valuation_layer 
            WHERE product_id = %s
        """, (line.product_id.id,))
        sql_qty, sql_val = self.env.cr.fetchone()

        # 2. AMBIL DATA DARI ORM (HALUSINASI CACHE)
        orm_qty = line.product_id.quantity_svl
        orm_val = line.product_id.value_svl

        # 3. DATA BARU YANG AKAN MASUK
        new_qty = line.counted_qty  # 34
        new_cost = line.unit_cost   # 20.000
        new_val = new_qty * new_cost

        # 4. HITUNG DUA SKENARIO
        # Skenario A: Jika Odoo pakai data SQL (0)
        hasil_a_qty = sql_qty + new_qty
        hasil_a_val = sql_val + new_val
        hasil_a_cost = hasil_a_val / hasil_a_qty if hasil_a_qty != 0 else 0

        # Skenario B: Jika Odoo pakai data Cache (152)
        hasil_b_qty = orm_qty + new_qty
        hasil_b_val = orm_val + new_val
        hasil_b_cost = hasil_b_val / hasil_b_qty if hasil_b_qty != 0 else 0

        logs = [
            f"=== HASIL UJI ASUMSI {target_code} ===",
            f"\nDATA SAAT INI:",
            f"1. Database SQL  : Qty {sql_qty} | Value {sql_val}",
            f"2. Cache Odoo    : Qty {orm_qty} | Value {orm_val}",
            f"\nTRANSAKSI BARU:",
            f"Masuk: {new_qty} pcs @ Rp {new_cost:,.2f} = Rp {new_val:,.2f}",
            f"\n------------------------------------------------",
            f"PREDIKSI HASIL AKHIR:",
            f"------------------------------------------------",
            f"A. JIKA PAKAI SQL (Database Murni):",
            f"   Rumus: ({sql_val} + {new_val}) / ({sql_qty} + {new_qty})",
            f"   Hasil: Rp {hasil_a_cost:,.2f}  <--- (HARAPAN KITA)",
            f"\nB. JIKA PAKAI CACHE (Halusinasi):",
            f"   Rumus: ({orm_val} + {new_val}) / ({orm_qty} + {new_qty})",
            f"   Hasil: Rp {hasil_b_cost:,.2f}  <--- (JIKA MASIH SALAH)",
            f"\n------------------------------------------------",
            f"KESIMPULAN:",
        ]

        if sql_qty == 0:
            logs.append("✅ Karena SQL sudah 0, saat Validate nanti Odoo terpaksa")
            logs.append("   membuka transaksi baru dan PASTI mengikuti Skenario A.")
            logs.append("   Angka 152 di Cache akan terbuang otomatis saat klik Validate.")
        else:
            logs.append("❌ Database ternyata belum 0. Hubungi Developer.")

        raise UserError("\n".join(logs))
    
    def action_total_purge_mismatched(self):
        self.ensure_one()
        logs = ["=== OPERASI PEMBERSIHAN TOTAL (BY PRODUCT ID) ==="]
        
        # 1. AMBIL SEMUA PRODUK DI BATCH INI
        product_ids = self.line_ids.mapped('product_id.id')
        if not product_ids:
            raise UserError("Batch kosong, Kak!")

        # 2. EKSEKUSI PEMBERSIHAN TANPA AMPUN (SQL)
        # Kita tidak peduli dia punya Move atau tidak. 
        # Selama dia produk di batch ini, kita nolkan sejarahnya.
        
        # A. Hapus SEMUA Layer (Uang & Qty SVL)
        self.env.cr.execute("DELETE FROM stock_valuation_layer WHERE product_id IN %s", (tuple(product_ids),))
        logs.append(f"✅ {self.env.cr.rowcount} Sejarah Nilai (SVL) dimusnahkan.")
        
        # B. Hapus SEMUA Pergerakan (Move & Line)
        # Hapus Move Line dulu (Detail)
        self.env.cr.execute("DELETE FROM stock_move_line WHERE product_id IN %s", (tuple(product_ids),))
        # Hapus Move (Dokumen)
        self.env.cr.execute("DELETE FROM stock_move WHERE product_id IN %s", (tuple(product_ids),))
        logs.append(f"✅ Semua jejak pergerakan fisik (Move) dibersihkan.")
        
        # C. Hapus Saldo Ringkasan (Quant)
        self.env.cr.execute("DELETE FROM stock_quant WHERE product_id IN %s", (tuple(product_ids),))
        logs.append(f"✅ Saldo On-Hand (Quant) di-reset ke 0.")

        # 3. RESET HARGA MASTER (ORM)
        products = self.env['product.product'].browse(product_ids)
        for prod in products:
            try:
                prod.sudo().with_context(disable_inventory_valuation=True).write({'standard_price': 0.0})
            except:
                pass
        logs.append(f"✅ Harga Master {len(product_ids)} produk di-reset ke 0.")

        # 4. FINALISASI
        self.env.cr.commit()
        self.env.cache.invalidate()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'BERSIH TOTAL, KAK!',
                'message': "\n".join(logs),
                'type': 'success',
                'sticky': True,
            }
        }
    def action_cleanup_ghost_only(self):
        """
        GHOST HUNTER MODE:
        Hapus Move, Move Line, dan Lot yang sudah tidak punya history pergerakan.
        """
        self.ensure_one()
        logs = ["=== PEMBERSIHAN HANTU (GHOST & LOT PURGE) ==="]
        
        # 1. CARI MOVE HANTU (Done tapi Gak Ada SVL)
        query_find_ghosts = """
            SELECT sm.id, sm.product_id
            FROM stock_move sm
            LEFT JOIN stock_valuation_layer svl ON svl.stock_move_id = sm.id
            WHERE sm.state = 'done'
            AND svl.id IS NULL
            AND sm.reference NOT LIKE 'WH/IN%%'
            AND sm.reference != %s
        """
        self.env.cr.execute(query_find_ghosts, (self.name.strip(),))
        ghost_moves = self.env.cr.dictfetchall()
        
        if not ghost_moves:
            logs.append("✅ Tidak ditemukan jejak Move hantu.")
        else:
            move_ids = [m['id'] for m in ghost_moves]
            product_ids = list(set([m['product_id'] for m in ghost_moves]))
            
            # A. HAPUS MOVE LINE & MOVE
            self.env.cr.execute("DELETE FROM stock_move_line WHERE move_id IN %s", (tuple(move_ids),))
            self.env.cr.execute("DELETE FROM stock_move WHERE id IN %s", (tuple(move_ids),))
            logs.append(f"👻 {len(move_ids)} Move Hantu dimusnahkan.")

            # B. HAPUS LOT HANTU (Lot yang sudah tidak punya Move Line sama sekali)
            # Kita bersihkan Lot yang "nganggur" supaya tidak nyampah di database
            query_purge_lots = """
                DELETE FROM stock_production_lot 
                WHERE id NOT IN (SELECT DISTINCT lot_id FROM stock_move_line WHERE lot_id IS NOT NULL)
                AND product_id IN %s
            """
            self.env.cr.execute(query_purge_lots, (tuple(product_ids),))
            logs.append(f"✅ {self.env.cr.rowcount} Lot Hantu (tanpa history) dibersihkan.")

            # C. SINKRONISASI SALDO (QUANT)
            self.env.cr.execute("DELETE FROM stock_quant WHERE product_id IN %s", (tuple(product_ids),))
            logs.append(f"✅ Saldo fisik produk terkait telah disinkronkan.")

        self.env.cr.commit()
        self.env.cache.invalidate()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Pembersihan Total Selesai',
                'message': "\n".join(logs),
                'type': 'success',
                'sticky': True,
            }
        }
    
    def action_basmi_hantu_final(self):
        """
        ODOO 16: PHYSICAL SYNC (TRIGGER 1, -1)
        Memaksa RAM sinkron melalui Adjustment, lalu hapus jejak SQL.
        """
        self.ensure_one()
        logs = ["=== ODOO 16: PHYSICAL SYNC MODE (FORCE RECOMPUTE) ==="]
        table_lot = 'stock_lot'

        # Ambil ID Lokasi agar filter leaf SQL/ORM aman
        inv_loc = self.env['stock.location'].search([('usage', '=', 'inventory')], limit=1)
        int_loc = self.env['stock.location'].search([('usage', '=', 'internal')], limit=1)
        
        if not inv_loc or not int_loc:
            raise UserError("Lokasi Inventory atau Internal tidak ditemukan!")

        inv_loc_id = inv_loc.id
        int_loc_id = int_loc.id

        for line in self.line_ids:
            product = line.product_id
            
            # 1. SQL PURGE AWAL (Kosongkan sejarah bermasalah)
            self.env.cr.execute("DELETE FROM stock_valuation_layer WHERE product_id = %s", (product.id,))
            self.env.cr.execute("DELETE FROM stock_move_line WHERE product_id = %s", (product.id,))
            self.env.cr.execute("DELETE FROM stock_move WHERE product_id = %s", (product.id,))
            self.env.cr.execute("DELETE FROM stock_quant WHERE product_id = %s", (product.id,))
            
            # 2. DUMMY TRANSACTION (Trigger RAM: Tambah 1, Kurang 1)
            # Jalur ini memaksa Odoo menjalankan fungsi _compute_quantities
            try:
                # Tambah 1 (Dummy In)
                q_in = self.env['stock.quant'].with_context(inventory_mode=True).sudo().create({
                    'product_id': product.id,
                    'location_id': int_loc_id,
                    'inventory_quantity': 1.0,
                })
                q_in.action_apply_inventory()
                
                # Kurang 1 (Dummy Out) - Kembalikan ke 0
                q_out = self.env['stock.quant'].sudo().search([
                    ('product_id', '=', product.id),
                    ('location_id', '=', int_loc_id)
                ], limit=1)
                
                if q_out:
                    q_out.with_context(inventory_mode=True).write({'inventory_quantity': 0.0})
                    q_out.action_apply_inventory()

                # 3. HAPUS JEJAK DUMMY (SQL TOTAL)
                # Menghapus semua pergerakan dummy tadi agar on-hand benar-benar 0 secara fisik dan history
                self.env.cr.execute("DELETE FROM stock_valuation_layer WHERE product_id = %s", (product.id,))
                self.env.cr.execute("DELETE FROM stock_move_line WHERE product_id = %s", (product.id,))
                self.env.cr.execute("DELETE FROM stock_move WHERE product_id = %s", (product.id,))
                self.env.cr.execute("DELETE FROM stock_quant WHERE product_id = %s", (product.id,))
                
                # Hapus Lot yang terbentuk dari dummy transaction
                self.env.cr.execute(f"""
                    DELETE FROM {table_lot} 
                    WHERE product_id = %s 
                    AND id NOT IN (SELECT DISTINCT lot_id FROM stock_move_line WHERE lot_id IS NOT NULL)
                """, (product.id,))

                logs.append(f"🎯 {product.default_code}: Physical Sync Selesai.")
            except Exception as e:
                logs.append(f"❌ {product.default_code}: Gagal Trigger ({str(e)})")

        # --- 4. DEEP RAM CLEANUP ---
        self.env.cr.commit()
        self.env.cache.invalidate()
        if hasattr(self.env.registry, 'clear_caches'):
            self.env.registry.clear_caches()
        
        # Paksa Invalidate Model agar Odoo 16 tidak mengambil data lama
        self.env['product.product'].invalidate_model()
        self.env['stock.quant'].invalidate_model()
        
        # Re-check Memory
        for line in self.line_ids:
            line.product_id.invalidate_recordset()
            _force_check = line.product_id.qty_available # Pancing RAM ambil data 0 dari DB

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'PHYSICAL SYNC OK!',
                'message': "\n".join(logs),
                'type': 'success',
                'sticky': True,
            }
        }
    def action_simulasi_seluruh_produk(self):
        self.ensure_one()
        report = ["=== LAPORAN SIMULASI MASSAL BATCH ===", ""]
        summary = {
            'clean': 0,
            'dirty': 0,
            'details': []
        }
        
        for line in self.line_ids:
            product = line.product_id
            
            # 1. Ambil Data SQL (Murni)
            self.env.cr.execute("""
                SELECT SUM(remaining_qty) FROM stock_valuation_layer 
                WHERE product_id = %s AND company_id = %s
            """, (product.id, self.env.company.id))
            sql_qty = self.env.cr.fetchone()[0] or 0.0
            
            # 2. Ambil Data Cache (Ingatan Odoo)
            cache_qty = product.quantity_svl
            
            # 3. Prediksi AVCO jika masuk barang baru (Asumsi 1 unit masuk)
            # Ini untuk ngetes apakah rumusnya bakal rusak atau tidak
            target_price = 20000 # Contoh harga simulasi
            if (sql_qty + 1) != 0:
                prediksi_avco = (0 + target_price) / (sql_qty + 1)
            else:
                prediksi_avco = 0

            status = "✅ CLEAN" if sql_qty == 0 and cache_qty == 0 else "❌ DIRTY"
            
            if status == "❌ DIRTY":
                summary['dirty'] += 1
                report.append(f"[{status}] {product.default_code}")
                report.append(f"   -> SQL: {sql_qty} | Cache: {cache_qty}")
            else:
                summary['clean'] += 1

        report.append("")
        report.append("=== RINGKASAN AKHIR ===")
        report.append(f"🟢 Produk Bersih : {summary['clean']}")
        report.append(f"🔴 Produk Bermasalah : {summary['dirty']}")
        
        if summary['dirty'] == 0:
            report.append("")
            report.append("KESIMPULAN: AMAN! Silakan klik VALIDATE.")
        else:
            report.append("")
            report.append("KESIMPULAN: JANGAN VALIDATE! Masih ada hantu.")

        raise UserError("\n".join(report))
    def action_purge_opening_lots_manual(self):
        """
        SPESIFIK LOT PURGER:
        Target: Menghapus Lot dengan nama 'Saldo Awal 1 November 2025'
        Fungsi: Membersihkan sejarah agar tidak bentrok saat Validate Saldo Awal.
        """
        self.ensure_one()
        target_lot_name = "Saldo Awal 1 November 2025" # Nama Lot spesifik dari Kakak
        logs = [f"=== PURGING SPECIFIC LOT: {target_lot_name} ==="]

        # 1. Cari semua ID Lot yang namanya persis seperti itu
        target_lots = self.env['stock.lot'].sudo().search([('name', '=', target_lot_name)])
        
        if not target_lots:
            # Kita ganti UserError jadi notif biasa saja biar tidak mengganggu flow
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'INFO',
                    'message': f'Lot "{target_lot_name}" sudah bersih atau memang tidak ditemukan.',
                    'type': 'warning',
                }
            }

        lot_ids = target_lots.ids

        # 2. EKSEKUSI PEMBERSIHAN NUKLIR (SQL)
        try:
            # A. Hapus Valuation (SVL) yang terhubung ke Lot tersebut
            self.env.cr.execute("""
                DELETE FROM stock_valuation_layer 
                WHERE stock_move_id IN (
                    SELECT move_id FROM stock_move_line WHERE lot_id IN %s
                )
            """, (tuple(lot_ids),))

            # B. Hapus Detail Pergerakan Fisik (Move Line & Quant)
            self.env.cr.execute("DELETE FROM stock_quant WHERE lot_id IN %s", (tuple(lot_ids),))
            self.env.cr.execute("DELETE FROM stock_move_line WHERE lot_id IN %s", (tuple(lot_ids),))
            
            # C. Hapus Master Lot-nya (The Heart of Identity)
            self.env.cr.execute("DELETE FROM stock_lot WHERE id IN %s", (tuple(lot_ids),))
            
            logs.append(f"✅ Berhasil memusnahkan {len(lot_ids)} record Lot '{target_lot_name}'.")
            
        except Exception as e:
            raise UserError(f"Gagal eksekusi SQL: {str(e)}")

        # 3. RESET CACHE TOTAL
        self.env.cr.commit()
        self.env.cache.invalidate()
        self.env['stock.lot'].invalidate_model()
        self.env['stock.quant'].invalidate_model()

        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'CLEANUP BERHASIL!',
                'message': "\n".join(logs),
                'type': 'success',
                'sticky': True,
            }
        }
    def action_force_sync_date_after_validate(self):
        """
        FORCE SYNC DATE (POST-VALIDATE)
        Fungsi ini digunakan jika batch sudah DONE tapi tanggalnya masih berantakan.
        Menyinkronkan semua tabel ke tanggal di Header Batch.
        """
        self.ensure_one()
        if self.state != 'done':
            raise UserError("Tombol ini hanya untuk Batch yang sudah berstatus DONE, Kak.")
        
        forced_date = self.date # Tanggal 1 November dari Header
        forced_date_str = fields.Datetime.to_string(forced_date)
        forced_date_only = forced_date.date()

        # 1. Cari Picking yang terbentuk dari Batch ini
        pickings = self.env['stock.picking'].search([('origin', '=', self.name)])
        if not pickings:
            raise UserError("Tidak ditemukan Picking terkait Batch ini.")

        try:
            for picking in pickings:
                # A. Update Picking & Stock Moves
                self.env.cr.execute("""
                    UPDATE stock_picking SET date_done = %s, date = %s WHERE id = %s
                """, (forced_date_str, forced_date_str, picking.id))
                
                self.env.cr.execute("""
                    UPDATE stock_move SET date = %s WHERE picking_id = %s
                """, (forced_date_str, picking.id))

                # B. Update Stock Move Lines (Detail Fisik & Lot)
                self.env.cr.execute("""
                    UPDATE stock_move_line SET date = %s WHERE picking_id = %s
                """, (forced_date_str, picking.id))

                # C. Update Valuation Layer (Uang/AVCO)
                self.env.cr.execute("""
                    UPDATE stock_valuation_layer SET create_date = %s 
                    WHERE stock_move_id IN (SELECT id FROM stock_move WHERE picking_id = %s)
                """, (forced_date_str, picking.id))

                # D. Update Account Move (Jurnal Akuntansi)
                # Mencari jurnal yang terhubung dengan SVL tadi
                self.env.cr.execute("""
                    UPDATE account_move SET date = %s 
                    WHERE id IN (
                        SELECT account_move_id FROM stock_valuation_layer 
                        WHERE stock_move_id IN (SELECT id FROM stock_move WHERE picking_id = %s)
                    )
                """, (forced_date_only, picking.id))

            # Commit & Clear Cache agar Odoo langsung menampilkan perubahan
            self.env.cr.commit()
            self.env.cache.invalidate()

            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'SINKRONISASI TANGGAL BERHASIL!',
                    'message': f'Seluruh data Picking, Move, Line, SVL, dan Jurnal dipaksa ke {forced_date_str}.',
                    'type': 'success',
                    'sticky': False,
                }
            }

        except Exception as e:
            raise UserError(f"Gagal melakukan sinkronisasi SQL: {str(e)}")
class StockOpeningSummary(models.Model):
    _name = 'stock.opening.summary'
    _description = 'Opening Balance Reconciliation Summary'
    _order = 'account_id asc'

    batch_id = fields.Many2one('stock.opening.batch', string='Batch', ondelete='cascade')
    
    to_override = fields.Boolean(
        string='Override Journal?', 
        default=True,
        help="Centang: Ganti akun kredit dengan akun jurnal asli (Wajib Balance).\n"
             "Tidak Centang: Pakai akun Inventory Adjustment default (Abaikan Balance)."
    )
    
    account_id = fields.Many2one('account.account', string='Account', required=True)
    inventory_value = fields.Float(string='Total Stock (Input)', digits='Product Price')
    journal_value = fields.Float(string='Journal Target', digits='Product Price')
    variance = fields.Float(string='Variance', digits='Product Price')
    currency_id = fields.Many2one(related='batch_id.currency_id')