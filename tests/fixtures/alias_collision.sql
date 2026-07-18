SELECT o.OrderID, o.TotalAmount FROM sales.Orders o WHERE o.IsActive = 1;
SELECT o.OfficeName, o.OfficeCode FROM hr.Offices o WHERE o.Region = 'CA';
SELECT p.ProductName FROM catalog.Products p;
SELECT p.PersonName FROM hr.People p;
