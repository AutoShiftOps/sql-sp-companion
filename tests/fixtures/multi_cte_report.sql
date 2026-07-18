/*
 * Fixture: multi-CTE reporting query.
 *
 * FICTIONAL. Invented for this test suite. Any resemblance to a real schema is
 * coincidental — see tests/fixtures/README.md before adding fixtures.
 *
 * Exercises: multi-CTE chain, CTE->CTE reference, [Bracketed Multi Word] names,
 * 3-part db.schema.table naming, WITH (NOLOCK), cross-schema LEFT JOIN chain,
 * quoted string aliases.
 */
;WITH PartyDetails AS
(
    SELECT Id as 'Party ID', Name as 'Party Name',
    ScheduledReviewDate as 'Scheduled Review Date'
    FROM dbo.Party
    WHERE Active=0  -- only fetch active ids
),
PartyRef AS
(
    SELECT PartyId, RefCode, CountryOfIncorporationId
    FROM dbo.PartyCompany WITH (NOLOCK)
),
Country AS
(SELECT Id, ShortName, Name as 'CountryName'
    FROM PartyRef
INNER JOIN dbo.Country country ON country.id = PartyRef.[CountryOfIncorporationId] ),
RegionRiskDetails AS
(
    SELECT PartyId as 'PID',
    rcs1.RiskCategoryIdentifier AS 'Regional Risk Rating',
    RegionComments AS [Region Comments]
    FROM risk.RatingDetails rrd
    LEFT JOIN risk.RiskCategory rcs1 ON rrd.RegionRiskRating = rcs1.Id
),
GroupRiskRating AS
(
    SELECT EntityId AS 'PID', [DerivedRiskOutcome] AS 'Group Risk Rating'
    from [PartyWarehouse].[risk].[CaseDerivedRisk]
    WHERE BusinessEntityTypeId=30
),
Products AS
(
    SELECT DISTINCT p.id, caseid, lpt.Name AS 'Product Type'
    FROM sales.Product p
    LEFT JOIN [refdata].[LookupProductType] lpt ON lpt.Id = p.[LookupProductTypeId]
    LEFT JOIN [dbo].[PartyAssociation] [pa] ON pa.EntityId = p.CaseId
)
SELECT DISTINCT
PD.[Party ID] AS 'Party ID',
PD.[Party Name] AS 'Party Name',
GRR.[Group Risk Rating] AS 'Group Risk Rating',
RRD.[Regional Risk Rating] AS 'Regional Risk Rating',
P.[Product Type] AS 'Product Type'
FROM Products P
INNER JOIN PartyDetails PD ON PD.[Party ID]=P.PID
LEFT JOIN RegionRiskDetails RRD ON PD.[Party ID] = RRD.PID
LEFT JOIN GroupRiskRating GRR ON PD.[Party ID] = GRR.PID
ORDER BY [Party ID]
