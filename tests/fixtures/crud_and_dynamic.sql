CREATE PROCEDURE warehouse.usp_ManageInventory @ProductID INT, @Qty INT AS BEGIN
    SELECT i.ProductID, i.StockLevel INTO #Snapshot FROM warehouse.Inventory i;

    UPDATE warehouse.Inventory
    SET StockLevel = StockLevel - @Qty, LastUpdated = GETDATE()
    WHERE ProductID = @ProductID;

    MERGE warehouse.StockTransfers AS target
    USING (SELECT WarehouseID, ProductID FROM warehouse.Inventory) AS src
    ON target.ProductID = src.ProductID
    WHEN MATCHED THEN UPDATE SET target.AvailableQty = 0;

    INSERT INTO audit.LowStockAlerts (ProductID, AlertDate) VALUES (@ProductID, GETDATE());
    DELETE FROM warehouse.StockTransfers WHERE LastSyncDate < DATEADD(DAY,-90,GETDATE());
    TRUNCATE TABLE staging.InventoryImport;
END
GO
CREATE PROCEDURE dbo.usp_DynamicSearch @tbl NVARCHAR(128) AS BEGIN
    SELECT c.CustomerID FROM dbo.Customers c;
    DECLARE @sql NVARCHAR(MAX) = N'SELECT * FROM ' + QUOTENAME(@tbl);
    EXEC sp_executesql @sql;
END
