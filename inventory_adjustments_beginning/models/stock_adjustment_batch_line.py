# -*- coding: utf-8 -*-
from odoo import api, fields, models
import logging

_logger = logging.getLogger(__name__)

class StockOpeningBatchLine(models.Model):
    _name = 'stock.opening.batch.line'
    _description = 'Opening Balance Batch Line'

    batch_id = fields.Many2one('stock.opening.batch', 'Opening Batch', required=True, ondelete='cascade')
    
    # 1. Product & Category (Visual Helper)
    product_id = fields.Many2one('product.product', 'Product', required=True)
    
    product_category_id = fields.Many2one(
        'product.category',
        string='Product Category',
        related='product_id.categ_id',
        store=True,
        readonly=True,
        help="Kategori Produk (Menentukan Akun Debit/Persediaan)"
    )
    
    # 2. Preview Akun Debit (X-Ray Vision)
    planned_debit_account_id = fields.Many2one(
        'account.account',
        string='Planned Debit (Est)',
        compute='_compute_planned_debit_account',
        help="Estimasi akun Persediaan yang akan didebit berdasarkan settingan Kategori."
    )

    # 3. Location & Lot
    location_id = fields.Many2one('stock.location', 'Location', required=True)
    lot_id = fields.Many2one('stock.lot', 'Lot/Serial Number', domain="[('product_id', '=', product_id)]")

    # 4. Quantities
    theoretical_qty = fields.Float('On Hand Quantity', readonly=True)
    counted_qty = fields.Float('Counted Quantity')
    difference = fields.Float('Difference', compute='_compute_difference', store=True)

    # 5. Valuation
    unit_cost = fields.Float(string='Unit Cost', digits='Product Price', default=0.0)
    currency_id = fields.Many2one(related='batch_id.currency_id', store=True, readonly=True)

    inventory_value = fields.Monetary(
        string='Inventory Value (Line)',
        compute='_compute_inventory_value',
        store=True,
        currency_field='currency_id',
        help="Nilai stok khusus untuk baris produk ini."
    )

    # =========================================================
    # THE MATCHING ENGINE (DATA ONLY - NO VARIANCE CALC)
    # =========================================================
    
    # A. SUMBER KEBENARAN (Source Jurnal)
    target_move_line_id = fields.Many2one(
        'account.move.line',
        string='Match Journal Item',
        help="Pilih baris jurnal referensi. Nilai Variance akan dihitung di Tab Summary (Header), bukan di sini.",
        domain="[('move_id', '=', parent.journal_entry_id), ('account_id.deprecated', '=', False)]"
    )

    # B. BAYANGAN / EXECUTER (Contra Account)
    contra_account_id = fields.Many2one(
        'account.account',
        string='Contra Account',
        help="Akun lawan (Kredit). Variance dihitung per Akun ini di Summary.",
        required=True
    )
    
    # C. TARGET VALUE (Hanya sebagai Info Referensi)
    target_accounting_value = fields.Monetary(
        string='Ref: Target GL Total',
        default=0.0,
        currency_field='currency_id',
        help="Nilai total dari Jurnal Referensi. Hanya info, tidak dikurangi per baris."
    )
    
    # D. VARIANCE AMOUNT -> DIHAPUS
    # Kita hapus field variance per baris agar user tidak bingung.
    # Variance akan muncul di Tabel Rekonsiliasi (Summary).

    # =========================================================
    # LOGIC 1: UI INTERACTION (ONCHANGE)
    # =========================================================

    @api.onchange('target_move_line_id')
    def _onchange_target_move_line(self):
        """Logic Normal: User pilih Baris Jurnal -> Isi Akun"""
        if self.target_move_line_id:
            # 1. Copy Akun
            self.contra_account_id = self.target_move_line_id.account_id.id
            # 2. Copy Nilai (Info Only)
            nilai = self.target_move_line_id.debit or abs(self.target_move_line_id.balance)
            self.target_accounting_value = nilai

    @api.onchange('contra_account_id')
    def _onchange_contra_account_id(self):
        """Reverse Logic (UI): User pilih Akun -> Cari Baris Jurnal Otomatis."""
        if self.contra_account_id and not self.target_move_line_id:
            journal_entry = False
            if self.batch_id and self.batch_id.journal_entry_id:
                journal_entry = self.batch_id.journal_entry_id
            
            if journal_entry:
                matching_line = self.env['account.move.line'].search([
                    ('move_id', '=', journal_entry.id),
                    ('account_id', '=', self.contra_account_id.id)
                ], limit=1)
                
                if matching_line:
                    self.target_move_line_id = matching_line.id
                    self.target_accounting_value = matching_line.debit or abs(matching_line.balance)

    @api.onchange('product_id')
    def _onchange_product_default_loc(self):
        if not self.location_id:
            warehouse = self.env['stock.warehouse'].search([('company_id', '=', self.env.company.id)], limit=1)
            if warehouse:
                self.location_id = warehouse.lot_stock_id.id

    # =========================================================
    # LOGIC 2: IMPORT SUPPORT (CREATE OVERRIDE)
    # =========================================================

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('contra_account_id') and not vals.get('target_move_line_id') and vals.get('batch_id'):
                batch = self.env['stock.opening.batch'].browse(vals['batch_id'])
                if batch.journal_entry_id:
                    matching_line = self.env['account.move.line'].search([
                        ('move_id', '=', batch.journal_entry_id.id),
                        ('account_id', '=', vals['contra_account_id'])
                    ], limit=1)
                    
                    if matching_line:
                        vals['target_move_line_id'] = matching_line.id
                        if not vals.get('target_accounting_value'):
                            vals['target_accounting_value'] = matching_line.debit or abs(matching_line.balance)
        return super().create(vals_list)

    # =========================================================
    # COMPUTE METHODS
    # =========================================================

    @api.depends('product_category_id')
    def _compute_planned_debit_account(self):
        for line in self:
            if line.product_category_id:
                line.planned_debit_account_id = line.product_category_id.property_stock_valuation_account_id
            else:
                line.planned_debit_account_id = False

    @api.depends('counted_qty', 'unit_cost')
    def _compute_inventory_value(self):
        for line in self:
            line.inventory_value = line.counted_qty * line.unit_cost

    @api.depends('counted_qty', 'theoretical_qty')
    def _compute_difference(self):
        for line in self:
            line.difference = line.counted_qty - line.theoretical_qty

    @api.onchange('product_id', 'location_id', 'lot_id')
    def _onchange_product_location(self):
        if self.product_id and self.location_id:
            quants = self.env['stock.quant']._gather(self.product_id, self.location_id, lot_id=self.lot_id)
            self.theoretical_qty = sum(quants.mapped('quantity'))
        else:
            self.theoretical_qty = 0