def migrate(cr, version):
    cr.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'zenlenet_binding' AND column_name = 'odoo_model'
        """
    )
    if cr.fetchone():
        cr.execute('ALTER TABLE zenlenet_binding RENAME COLUMN odoo_model TO obss_model')
    cr.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'zenlenet_binding' AND column_name = 'source'
        """
    )
    if cr.fetchone():
        cr.execute("UPDATE zenlenet_binding SET source = 'obss' WHERE source = 'odoo'")
    cr.execute(
        """
        UPDATE ir_model_data
           SET name = 'login_layout_no_obss'
         WHERE module = 'zenlenet_ops' AND name = 'login_layout_no_odoo'
        """
    )
    cr.execute(
        """
        UPDATE ir_model_data
           SET name = 'brand_promotion_no_obss'
         WHERE module = 'zenlenet_ops' AND name = 'brand_promotion_no_odoo'
        """
    )
