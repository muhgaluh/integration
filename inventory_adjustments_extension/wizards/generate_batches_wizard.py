# -*- coding: utf-8 -*-
from odoo import api, fields, models, _
from odoo.exceptions import UserError
from collections import defaultdict
import math

class GenerateBatchesWizard(models.TransientModel):
    _name = 'generate.batches.wizard'
    _description = 'Wizard to Generate Inventory Count Batches'

    location_id = fields.Many2one(
        'stock.location',
        string='Location',
        required=True,
        domain="[('usage', '=', 'internal')]"
    )
    batch_name_prefix = fields.Char(
        string='Batch Name Prefix',
        required=True,
        default='Count'
    )
    max_lines_per_batch = fields.Integer(
        string='Max Lines per Batch',
        required=True,
        default=1000
    )
    filter_type = fields.Selection([
        ('all', 'All Storable Products'),
        ('category', 'Specific Category')
    ], string='Product Filter', default='all', required=True)
    
    product_categ_id = fields.Many2one(
        'product.category',
        string='Product Category'
    )
    
    group_by_field = fields.Selection([
        ('none', 'No Grouping (Simple Split)'),
        ('category', 'Group by Product Category')
    ], string='Group By', default='category', required=True)

    
    def action_generate_batches(self):
        self.ensure_one()
        if self.max_lines_per_batch <= 0:
            raise UserError(_("Max lines per batch must be greater than 0."))

        # Step 1: Find all eligible products
        product_domain = [('type', '=', 'product')] # Storable Products
        if self.filter_type == 'category':
            if not self.product_categ_id:
                raise UserError(_("You must select a Product Category."))
            product_domain.append(('categ_id', 'child_of', self.product_categ_id.id))

        all_products = self.env['product.product'].search(product_domain)
        if not all_products:
            raise UserError(_("No products found matching these criteria."))

        # Step 2: Group products based on the "Group By" setting
        grouped_products = defaultdict(list)
        if self.group_by_field == 'category':
            # Group products by their category record
            for product in all_products.sorted(key=lambda p: p.categ_id.id):
                grouped_products[product.categ_id].append(product)
        else:
            # No grouping, put all products in a single 'None' group
            grouped_products[None] = all_products

        Batch = self.env['stock.adjustment.batch']
        BatchLine = self.env['stock.adjustment.batch.line']
        created_batches_ids = []

        # Step 3: Iterate through each group and create batches
        for group_key, products_in_group in grouped_products.items():
            
            total_products = len(products_in_group)
            total_parts = math.ceil(total_products / self.max_lines_per_batch)

            # Split the group into chunks of 'max_lines_per_batch'
            for i in range(0, total_products, self.max_lines_per_batch):
                product_chunk = products_in_group[i : i + self.max_lines_per_batch]
                
                # --- Create the Batch ---
                new_batch = Batch.create({
                    'reason': self.batch_name_prefix,
                    'user_id': self.env.user.id,
                    'state': 'draft',
                    'location_id': self.location_id.id,
                })

                # Tentukan nama batch yang deskriptif
                batch_name = f"{new_batch.name} - {self.batch_name_prefix}"
                if group_key:
                    batch_name += f" - {group_key.name}"
                
                if total_parts > 1:
                    part_num = (i // self.max_lines_per_batch) + 1
                    batch_name += f" (Part {part_num}/{total_parts})"
                
                new_batch.write({'name': batch_name})

                # --- Create Batch Lines (in bulk) ---
                lines_to_create = []
                for product in product_chunk:
                    lines_to_create.append({
                        'batch_id': new_batch.id,
                        'product_id': product.id,
                        # 'location_id': self.location_id.id,
                    })
                
                new_lines = BatchLine.create(lines_to_create)
                
                # ----------------------------------------
                # INI ADALAH PERBAIKANNYA
                # ----------------------------------------
                # PENTING: Picu onchange secara manual untuk mengisi theoretical_qty
                # Kita harus me-loop setiap baris karena onchange mengharapkan singleton
                
                # BARIS LAMA YANG SALAH:
                # new_lines._onchange_product_location()
                
                # PERBAIKAN (LOOP):
                for line in new_lines:
                    line._onchange_product_location()
                # ----------------------------------------

                created_batches_ids.append(new_batch.id)

        # Step 4: Return an action to show the newly created batches
        if not created_batches_ids:
            return {'type': 'ir.actions.act_window_close'}
            
        return {
            'name': _('Generated Adjustment Batches'),
            'type': 'ir.actions.act_window',
            'res_model': 'stock.adjustment.batch',
            'view_mode': 'tree,form',
            'domain': [('id', 'in', created_batches_ids)],
        }