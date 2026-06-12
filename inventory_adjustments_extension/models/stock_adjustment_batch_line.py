# -*- coding: utf-8 -*-
from odoo import api, fields, models

class StockAdjustmentBatchLine(models.Model):
    _name = 'stock.adjustment.batch.line'
    _description = 'Stock Adjustment Batch Line'

    batch_id = fields.Many2one('stock.adjustment.batch', 'Adjustment Batch', required=True, ondelete='cascade')
    product_id = fields.Many2one('product.product', 'Product', required=True)
    location_id = fields.Many2one(
        'stock.location', 
        string='Location', 
        related='batch_id.location_id', 
        store=True, 
        readonly=True
    )
    lot_id = fields.Many2one('stock.lot', 'Lot/Serial Number', domain="[('product_id', '=', product_id)]")

    theoretical_qty = fields.Float('On Hand Quantity', readonly=True)
    counted_qty = fields.Float('Counted Quantity')
    difference = fields.Float('Difference', compute='_compute_difference', store=True)

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