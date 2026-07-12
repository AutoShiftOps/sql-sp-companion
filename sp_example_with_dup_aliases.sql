-- ============================================================
-- TEST FILE: sp_analyzer_v3 — Full Coverage Test
-- Dialects : T-SQL (SQL Server)
-- Schemas : dbo, sales, catalog, warehouse, audit, hr
-- Covers : Physical tables, CTEs, Temp tables (#),
-- JOINs, MERGE, TRUNCATE, Dynamic SQL warning,
-- Multi-schema refs, aliases, INSERT/UPDATE/DELETE
-- ============================================================

-- ============================================================
-- SP 1: Order Processing (CTE + Temp + Multi-schema + Audit)
-- ============================================================
CREATE PROCEDURE sales.usp_ProcessOrders
@CustomerID INT,
@StartDate DATE,
@EndDate DATE
AS
BEGIN
SET NOCOUNT ON;

-- Temp staging table (should appear as WARNING only)
CREATE TABLE #StagedOrders (
OrderID INT,
ProductID INT,
Quantity INT,
UnitPrice DECIMAL(10,2),
LineTotal AS (Quantity * UnitPrice)
);

-- CTE: recent high-value orders (should appear in CTEs tab only)
WITH HighValueOrders AS (
SELECT
o.OrderID,
o.CustomerID,
o.OrderDate,
o.TotalAmount
FROM sales.Orders o
INNER JOIN sales.Orders ord ON ord.CustomerID = o.CustomerID -- duplicate alias for same table
WHERE o.OrderDate BETWEEN @StartDate AND @EndDate
AND o.TotalAmount > 500
)
-- Load physical data via CTE into temp
INSERT INTO #StagedOrders (OrderID, ProductID, Quantity, UnitPrice)
SELECT
od.OrderID,
od.ProductID,
od.Quantity,
od.UnitPrice
FROM HighValueOrders hvo
INNER JOIN sales.OrderDetails od ON od.OrderID = hvo.OrderID
INNER JOIN catalog.Products p ON p.ProductID = od.ProductID
WHERE p.IsActive = 1;

-- Final result from temp + physical tables
SELECT
s.OrderID,
c.CustomerName,
c.Email,
c.PhoneNumber,
p.ProductName,
p.Category,
p.UnitCost,
s.Quantity,
s.UnitPrice,
a.City,
a.Country,
a.PostalCode
FROM #StagedOrders s
INNER JOIN dbo.Customers c ON c.CustomerID = @CustomerID
INNER JOIN catalog.Products p ON p.ProductID = s.ProductID
LEFT JOIN dbo.Addresses a ON a.CustomerID = c.CustomerID;

-- Update last accessed timestamp
UPDATE sales.Orders
SET LastAccessedDate = GETDATE(),
ModifiedBy = SYSTEM_USER
WHERE CustomerID = @CustomerID;

-- Audit trail
INSERT INTO audit.ActivityLog (EntityType, EntityID, Action, ActionDate, PerformedBy)
VALUES ('ORDER', @CustomerID, 'PROCESS', GETDATE(), SYSTEM_USER);

-- Cleanup
DROP TABLE IF EXISTS #StagedOrders;
END
GO

-- ============================================================
-- SP 2: Inventory Management (SELECT INTO #temp + MERGE)
-- ============================================================
CREATE PROCEDURE warehouse.usp_ManageInventory
@ProductID INT,
@Qty INT,
@WarehouseID INT
AS
BEGIN
SET NOCOUNT ON;

-- Snapshot current stock into temp (warning only)
SELECT
i.ProductID,
i.WarehouseID,
i.StockLevel,
i.ReorderPoint,
i.LastUpdated
INTO #StockSnapshot
FROM warehouse.Inventory i
INNER JOIN warehouse.Inventory inv ON inv.ProductID = i.ProductID -- duplicate alias
WHERE i.ProductID = @ProductID
AND i.WarehouseID = @WarehouseID;

-- Deduct stock
UPDATE warehouse.Inventory
SET StockLevel = StockLevel - @Qty,
LastUpdated = GETDATE()
WHERE ProductID = @ProductID
AND WarehouseID = @WarehouseID;

-- Cross-warehouse rebalancing via MERGE
MERGE warehouse.StockTransfers AS target
USING (
SELECT
w.WarehouseID,
w.ProductID,
w.StockLevel
FROM warehouse.Inventory w
WHERE w.ProductID = @ProductID
AND w.StockLevel > w.ReorderPoint * 2
) AS src
ON target.ProductID = src.ProductID
AND target.WarehouseID = src.WarehouseID
WHEN MATCHED THEN
UPDATE SET target.AvailableQty = src.StockLevel,
target.LastSyncDate = GETDATE()
WHEN NOT MATCHED BY TARGET THEN
INSERT (ProductID, WarehouseID, AvailableQty, LastSyncDate)
VALUES (src.ProductID, src.WarehouseID, src.StockLevel, GETDATE());

-- Low stock alert
IF EXISTS (SELECT 1 FROM #StockSnapshot WHERE StockLevel < ReorderPoint)
BEGIN
INSERT INTO audit.LowStockAlerts (ProductID, WarehouseID, StockLevel, AlertDate)
SELECT ProductID, WarehouseID, StockLevel, GETDATE()
FROM warehouse.Inventory
WHERE ProductID = @ProductID
AND WarehouseID = @WarehouseID;
END

-- Remove stale transfer records
DELETE FROM warehouse.StockTransfers
WHERE ProductID = @ProductID
AND LastSyncDate < DATEADD(DAY, -90, GETDATE());

DROP TABLE IF EXISTS #StockSnapshot;
END
GO

-- ============================================================
-- SP 3: HR & Customer Reporting (Multi-CTE + TRUNCATE + DELETE)
-- ============================================================
CREATE PROCEDURE hr.usp_GenerateCustomerReport
@RegionID INT,
@FiscalYear INT
AS
BEGIN
SET NOCOUNT ON;

-- Multi-CTE chain
WITH RegionalCustomers AS (
SELECT
c.CustomerID,
c.CustomerName,
c.Email,
c.Segment,
c.RegionID
FROM dbo.Customers c
INNER JOIN dbo.Customers cust ON cust.CustomerID = c.CustomerID -- duplicate alias outside CTE
WHERE c.RegionID = @RegionID
AND c.IsActive = 1
),
CustomerOrders AS (
SELECT
rc.CustomerID,
rc.CustomerName,
rc.Segment,
SUM(o.TotalAmount) AS TotalSpend,
COUNT(o.OrderID) AS OrderCount,
MAX(o.OrderDate) AS LastOrderDate
FROM RegionalCustomers rc
INNER JOIN sales.Orders o ON o.CustomerID = rc.CustomerID
WHERE YEAR(o.OrderDate) = @FiscalYear
GROUP BY rc.CustomerID, rc.CustomerName, rc.Segment
)
SELECT
co.CustomerID,
co.CustomerName,
co.Segment,
co.TotalSpend,
co.OrderCount,
co.LastOrderDate,
a.City,
a.Country,
t.TerritoryName,
t.RegionManager
FROM CustomerOrders co
LEFT JOIN dbo.Addresses a ON a.CustomerID = co.CustomerID
LEFT JOIN hr.Territories t ON t.RegionID = @RegionID;

-- Refresh summary table
TRUNCATE TABLE dbo.CustomerSummaryCache;

INSERT INTO dbo.CustomerSummaryCache (CustomerID, TotalSpend, OrderCount, FiscalYear, GeneratedAt)
SELECT
o.CustomerID,
SUM(o.TotalAmount),
COUNT(o.OrderID),
@FiscalYear,
GETDATE()
FROM sales.Orders o
INNER JOIN sales.Orders ord ON ord.CustomerID = o.CustomerID -- duplicate alias for same table
INNER JOIN dbo.Customers c ON c.CustomerID = o.CustomerID
WHERE c.RegionID = @RegionID
AND YEAR(o.OrderDate) = @FiscalYear
GROUP BY o.CustomerID;

-- Upsert regional summary
MERGE hr.RegionalSummary AS target
USING (
SELECT
c.RegionID,
COUNT(DISTINCT c.CustomerID) AS CustomerCount,
SUM(o.TotalAmount) AS RegionRevenue
FROM dbo.Customers c
INNER JOIN dbo.Customers cust ON cust.CustomerID = c.CustomerID -- duplicate alias outside CTE
INNER JOIN sales.Orders o ON o.CustomerID = c.CustomerID
WHERE c.RegionID = @RegionID
AND YEAR(o.OrderDate) = @FiscalYear
GROUP BY c.RegionID
) AS src ON target.RegionID = src.RegionID AND target.FiscalYear = @FiscalYear
WHEN MATCHED THEN
UPDATE SET target.CustomerCount = src.CustomerCount,
        target.RegionRevenue = src.RegionRevenue,
        target.UpdatedAt = GETDATE()
WHEN NOT MATCHED THEN
INSERT (RegionID, FiscalYear, CustomerCount, RegionRevenue, UpdatedAt)
VALUES (src.RegionID, @FiscalYear, src.CustomerCount, src.RegionRevenue, GETDATE());

-- Purge old cache entries
DELETE FROM dbo.CustomerSummaryCache
WHERE FiscalYear < @FiscalYear - 3;

-- Audit
INSERT INTO audit.ActivityLog (EntityType, EntityID, Action, ActionDate, PerformedBy)
VALUES ('REPORT', @RegionID, 'GENERATE', GETDATE(), SYSTEM_USER);
END
GO

-- ============================================================
-- SP 4: Dynamic SQL example (should flag ⚠ dynamic SQL warning)
-- ============================================================
CREATE PROCEDURE dbo.usp_DynamicSearch
@TableName NVARCHAR(128),
@FilterCol NVARCHAR(128),
@FilterValue NVARCHAR(256)
AS
BEGIN
SET NOCOUNT ON;

-- Static physical table lookup first
SELECT
sl.SearchID,
sl.TableName,
sl.ExecutedBy,
sl.ExecutedAt
FROM audit.SearchLog sl
WHERE sl.TableName = @TableName;

-- Dynamic SQL — analyzer will flag this as ⚠ warning
DECLARE @SQL NVARCHAR(MAX);
SET @SQL = N'SELECT * FROM ' + QUOTENAME(@TableName) +
N' WHERE ' + QUOTENAME(@FilterCol) +
N' = @val';

EXEC sp_executesql @SQL, N'@val NVARCHAR(256)', @val = @FilterValue;

-- Log the search
INSERT INTO audit.SearchLog (TableName, FilterColumn, FilterValue, ExecutedBy, ExecutedAt)
VALUES (@TableName, @FilterCol, @FilterValue, SYSTEM_USER, GETDATE());
END
GO