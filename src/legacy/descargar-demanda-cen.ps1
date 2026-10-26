param(
    [Parameter()]
    [string]$StartDate = '2024-06-01',

    [Parameter()]
    [string]$EndDate = '2024-06-01',

    [Parameter()]
    [string]$OutputDirectory = (Join-Path (Get-Location) 'data-pruebaA-demanda-real')
)

$ErrorActionPreference = 'Stop'

foreach ($date in @($StartDate, $EndDate)) {
    $parsedDate = [datetime]::MinValue
    if (-not [datetime]::TryParseExact(
        $date,
        'yyyy-MM-dd',
        [Globalization.CultureInfo]::InvariantCulture,
        [Globalization.DateTimeStyles]::None,
        [ref]$parsedDate
    )) {
        throw "Fecha inválida: '$date'. Usa el formato YYYY-MM-DD."
    }
}

if ([datetime]::ParseExact($EndDate, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture) -lt
    [datetime]::ParseExact($StartDate, 'yyyy-MM-dd', [Globalization.CultureInfo]::InvariantCulture)) {
    throw 'EndDate debe ser igual o posterior a StartDate.'
}

if (Test-Path -LiteralPath $OutputDirectory) {
    throw "La carpeta de salida ya existe; el script no sobrescribe datos: $OutputDirectory"
}

New-Item -ItemType Directory -Path $OutputDirectory | Out-Null

$secureKey = Read-Host 'API key del CEN (entrada oculta)' -AsSecureString
$keyPointer = [IntPtr]::Zero
$apiKey = $null

try {
    $keyPointer = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureKey)
    $apiKey = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($keyPointer)

    $endpoint = 'https://sipub.api.coordinador.cl/demanda-real-estimada/v4/findByDate'
    $limit = 10000
    $manifest = [System.Collections.Generic.List[object]]::new()
    # `/demanda-real-estimada/v4/findByDate` was empirically verified as zero-based.
    $page = 0
    $totalPages = $null

    do {
        $query = @(
            'startDate=' + [uri]::EscapeDataString($StartDate)
            'endDate=' + [uri]::EscapeDataString($EndDate)
            'page=' + $page
            'limit=' + $limit
            'user_key=' + [uri]::EscapeDataString($apiKey)
        ) -join '&'
        $requestUri = $endpoint + '?' + $query
        $pagePath = Join-Path $OutputDirectory ('page-{0:D3}.json' -f $page)
        $responseObject = $null
        $succeeded = $false

        for ($attempt = 1; $attempt -le 3 -and -not $succeeded; $attempt++) {
            try {
                Invoke-WebRequest -Uri $requestUri -Method Get -TimeoutSec 120 -OutFile $pagePath -UseBasicParsing | Out-Null
                $responseObject = Get-Content -LiteralPath $pagePath -Raw | ConvertFrom-Json

                if ($null -eq $responseObject.data) {
                    throw 'La respuesta no contiene el campo data.'
                }

                if ($null -eq $responseObject.totalPages -or
                    $null -eq $responseObject.page -or
                    $null -eq $responseObject.limit) {
                    throw 'La respuesta no contiene los metadatos de paginación esperados.'
                }

                if ([int]$responseObject.page -ne $page -or [int]$responseObject.limit -ne $limit) {
                    throw 'La respuesta no coincide con la página o el límite solicitado.'
                }

                if ($null -eq $totalPages) {
                    $totalPages = [int]$responseObject.totalPages
                } elseif ([int]$responseObject.totalPages -ne $totalPages) {
                    throw 'El total de páginas cambió durante la extracción; revisa si los datos se actualizaron.'
                }

                $manifest.Add([pscustomobject]@{
                    page = $page
                    rows = @($responseObject.data).Count
                    totalPages = [int]$responseObject.totalPages
                    downloadedAt = (Get-Date).ToString('yyyy-MM-ddTHH:mm:ssK')
                })
                $succeeded = $true
            } catch {
                if (Test-Path -LiteralPath $pagePath) {
                    Remove-Item -LiteralPath $pagePath -Force
                }
                if ($attempt -lt 3) {
                    Start-Sleep -Seconds (2 * $attempt)
                } else {
                    throw "Falló la descarga de la página $page (error $($_.Exception.GetType().Name)); revisa autenticación y conectividad."
                }
            }
        }

        if (($page % 5) -eq 0 -or $page -eq 1 -or $page -eq $totalPages) {
            Write-Host ("Descargadas {0}/{1} páginas; {2} filas en la última página." -f $page, $totalPages, $manifest[-1].rows)
        }

        $page++
    } while ($page -lt $totalPages)

    $manifestPath = Join-Path $OutputDirectory 'manifest.json'
    $manifest | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath $manifestPath -Encoding utf8
    $rowCount = ($manifest | Measure-Object -Property rows -Sum).Sum
    Write-Host "Extracción terminada: $rowCount filas en $($manifest.Count) páginas. Manifiesto: $manifestPath"
} finally {
    if ($keyPointer -ne [IntPtr]::Zero) {
        [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($keyPointer)
    }
    $apiKey = $null
    $secureKey = $null
}
