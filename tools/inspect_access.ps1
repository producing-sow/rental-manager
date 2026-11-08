param(
    [Parameter(Mandatory = $true)]
    [string]$Path,
    [string]$OutDir = "",
    [string]$DatabasePassword = ""
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$connectionString = "Provider=Microsoft.Jet.OLEDB.4.0;Data Source=$Path;Mode=Read;"
if ($DatabasePassword) {
    $connectionString += "Jet OLEDB:Database Password=$DatabasePassword;"
}
$connection = New-Object System.Data.OleDb.OleDbConnection $connectionString
$connection.Open()

try {
    $tables = $connection.GetOleDbSchemaTable(
        [System.Data.OleDb.OleDbSchemaGuid]::Tables,
        $null
    ) | Where-Object { -not $_.TABLE_NAME.StartsWith("MSys") }

    $result = @()
    foreach ($table in $tables) {
        $name = [string]$table.TABLE_NAME
        $quoted = "[" + $name.Replace("]", "]]") + "]"
        $count = 0
        try {
            $command = $connection.CreateCommand()
            $command.CommandText = "SELECT COUNT(*) FROM $quoted"
            $count = [int]$command.ExecuteScalar()
            $command.Dispose()
        }
        catch {
            $count = -1
        }

        $columns = $connection.GetOleDbSchemaTable(
            [System.Data.OleDb.OleDbSchemaGuid]::Columns,
            @($null, $null, $name, $null)
        )

        $result += [pscustomobject]@{
            name = $name
            type = [string]$table.TABLE_TYPE
            rows = $count
            columns = @($columns | ForEach-Object {
                [pscustomobject]@{
                    name = [string]$_.COLUMN_NAME
                    type = [string]$_.DATA_TYPE
                    size = $_.CHARACTER_MAXIMUM_LENGTH
                }
            })
        }
    }

    $result | ConvertTo-Json -Depth 8

    if ($OutDir) {
        New-Item -ItemType Directory -Force -Path $OutDir | Out-Null
        foreach ($item in $result) {
            if ($item.rows -le 0) { continue }
            $safeName = $item.name -replace '[\\/:*?"<>|]', '_'
            $query = "SELECT * FROM [" + $item.name.Replace("]", "]]") + "]"
            $adapter = New-Object System.Data.OleDb.OleDbDataAdapter $query, $connection
            $dataSet = New-Object System.Data.DataSet
            [void]$adapter.Fill($dataSet)
            $dataSet.Tables[0] | Export-Csv -LiteralPath (Join-Path $OutDir ($safeName + ".csv")) -NoTypeInformation -Encoding UTF8
            $adapter.Dispose()
        }
    }
}
finally {
    $connection.Close()
    $connection.Dispose()
}
