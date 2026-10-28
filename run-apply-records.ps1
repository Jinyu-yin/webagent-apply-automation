$baseUrl = "http://127.0.0.1:8080/api/v2/apply-record"
$headers = @{ "Content-Type" = "application/json" }
$log = ".\apply-record-results.ndjson"
$maxRecords = 100  # Test 100 records

# Prerequisites
if (-not (Test-Path ".\payloads.ndjson")) { 
    Write-Error "payloads.ndjson not found"; 
    exit 1 
}

$allLines = [System.IO.File]::ReadAllLines(".\payloads.ndjson")
$totalLines = $allLines.Length
$testCount = [Math]::Min($maxRecords, $totalLines)

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Total lines in payloads.ndjson: $totalLines" -ForegroundColor Cyan
Write-Host "Will test: $testCount records" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

if (Test-Path $log) { Remove-Item $log }

$successCount = 0
$failCount = 0
$counter = 0

# Process records one by one (serial execution)
for ($i = 0; $i -lt $testCount; $i++) {
    $counter++
    $json = $allLines[$i]
    
    Write-Host "`n[Record $counter/$testCount] Processing..." -ForegroundColor Yellow
    
    try {
        # Parse JSON to show email
        $payload = $json | ConvertFrom-Json
        $email = $payload.email
        Write-Host "  Email: $email" -ForegroundColor Gray
        
        # Make API call
        $res = Invoke-RestMethod -Uri $baseUrl -Method Post -Headers $headers -Body $json -TimeoutSec 60
        
        # Extract apply_record_id
        $recordId = $res.apply_record_id
        $status = $res.status
        $isExisting = $res.is_existing
        
        # Save immediately
        $out = ($res | ConvertTo-Json -Depth 6 -Compress)
        Add-Content -Path $log -Value $out -Encoding UTF8
        
        $successCount++
        
        Write-Host "  [SUCCESS] Record ID: $recordId, Status: $status, Existing: $isExisting" -ForegroundColor Green
        Write-Host "  Saved to: $log" -ForegroundColor Gray
        
    } catch {
        $failCount++
        $errorMsg = $_.Exception.Message
        Write-Host "  [FAILED] Error: $errorMsg" -ForegroundColor Red
        
        # Save error info
        $errorJson = @{
            error = $errorMsg
            payload = ($json | ConvertFrom-Json)
            timestamp = (Get-Date -Format "yyyy-MM-dd HH:mm:ss")
        } | ConvertTo-Json -Depth 6 -Compress
        Add-Content -Path $log -Value $errorJson -Encoding UTF8
    }
    
    # Progress summary
    Write-Host "  Progress: Success=$successCount, Failed=$failCount" -ForegroundColor Cyan
    
    # Small delay to avoid overwhelming the server
    Start-Sleep -Milliseconds 200
}

# Final summary
Write-Host "`n========================================" -ForegroundColor Cyan
Write-Host "FINAL SUMMARY" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "Total processed: $testCount" -ForegroundColor White
Write-Host "Success: $successCount" -ForegroundColor Green
Write-Host "Failed: $failCount" -ForegroundColor Red

if (Test-Path $log) {
    $savedLines = (Get-Content $log).Count
    Write-Host "`nResults saved to: $log" -ForegroundColor Green
    Write-Host "Total lines in log: $savedLines" -ForegroundColor Green
} else {
    Write-Host "`nWARNING: No log file generated: $log" -ForegroundColor Red
}
