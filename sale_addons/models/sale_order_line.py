from odoo import models, fields, api


class SaleOrderLine(models.Model):
    _inherit = 'sale.order.line'

    stock_status = fields.Selection([
        ('available', 'Available'),
        ('partial_available', 'Partial Available'),
        ('partial_reserved', 'Partial Reserved'),
        ('reserved', 'Reserved'),
        ('done', 'Done'),
        ('unavailable', 'Out of Stock'),
    ], string='Stock Status',
       compute='_compute_stock_status')

    # @api.depends('product_id', 'product_uom_qty', 'order_id.state')
    # def _compute_stock_status(self):

    #     for line in self:

    #         if not line.product_id:
    #             line.stock_status = False
    #             continue

    #         # SO sudah dikonfirmasi
    #         if line.order_id.state in ('sale', 'done'):

    #             reserved_qty = sum(
    #                 line.move_ids.mapped('reserved_availability')
    #             )

    #             if reserved_qty >= line.product_uom_qty:
    #                 line.stock_status = 'reserved'
    #                 continue

    #         forecast_qty = line.product_id.virtual_available

    #         if forecast_qty <= 0:
    #             line.stock_status = 'unavailable'

    #         elif forecast_qty < line.product_uom_qty:
    #             line.stock_status = 'partial'

    #         else:
    #             line.stock_status = 'available'

    @api.depends('product_id','product_uom_qty','order_id.state','move_ids.state','move_ids.reserved_availability')
    def _compute_stock_status(self):

        for line in self:

            if not line.product_id:
                line.stock_status = False
                continue

            qty = line.product_uom_qty

            # ==========================
            # QUOTATION (Draft)
            # ==========================
            if line.order_id.state in ('draft', 'sent'):

                # available_qty = line.product_id.qty_available

                available_qty = line.product_id.with_context(
                    warehouse=line.order_id.warehouse_id.id
                ).free_qty

                if available_qty <= 0:
                    line.stock_status = 'unavailable'

                elif available_qty < qty:
                    line.stock_status = 'partial_available'

                else:
                    line.stock_status = 'available'

                continue

            # ==========================
            # DELIVERY COMPLETED
            # ==========================

            moves = line.move_ids.filtered(
                lambda m: m.state != 'cancel'
            )

            if moves and all(
                move.state == 'done'
                for move in moves
            ):
                line.stock_status = 'done'
                continue

            # ==========================
            # RESERVED STATUS
            # ==========================

            reserved_qty = sum(
                moves.mapped('reserved_availability')
            )

            if reserved_qty >= qty:
                line.stock_status = 'reserved'

            elif reserved_qty > 0:
                line.stock_status = 'partial_reserved'

            else:
                line.stock_status = 'unavailable'
            
            
            # ==========================
            # SALES ORDER (Confirmed)
            # ==========================
            # moves = line.move_ids.filtered(
            #     lambda m: m.state not in ('cancel',)
            # )

            # reserved_qty = sum(
            #     moves.mapped('reserved_availability')
            # )

            # if reserved_qty >= qty:
            #     line.stock_status = 'reserved'

            # elif reserved_qty > 0:
            #     line.stock_status = 'partial_reserved'

            # else:
            #     line.stock_status = 'unavailable'