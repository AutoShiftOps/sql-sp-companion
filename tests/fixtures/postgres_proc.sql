CREATE OR REPLACE FUNCTION public.fn_recent_orders(p_days INT)
RETURNS TABLE (order_id INT) AS $$
BEGIN
    RETURN QUERY
    SELECT o.order_id FROM public.orders o
    INNER JOIN public.customers c ON c.id = o.customer_id
    WHERE o.created_at > NOW() - (p_days || ' days')::INTERVAL;
END;
$$ LANGUAGE plpgsql;
