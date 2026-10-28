$baseUrl = "http://127.0.0.1:8080/api/v2"
$headers = @{ "Content-Type" = "application/json" }
$resultsLog = ".\full-pipeline-results.ndjson"

# 检查结果文件是否存在
if (-not (Test-Path ".\apply-record-results.ndjson")) {
    Write-Host "错误: apply-record-results.ndjson 不存在，请先运行 run-apply-records.ps1" -ForegroundColor Red
    exit 1
}

# 读取所有申请记录ID
$records = Get-Content ".\apply-record-results.ndjson" | ForEach-Object {
    try {
        $json = $_ | ConvertFrom-Json
        if ($json.apply_record_id) {
            [PSCustomObject]@{
                apply_record_id = $json.apply_record_id
                email = $json.email
                password = $json.password
                application_url = $json.application_url
            }
        }
    } catch {
        Write-Warning "解析失败: $_"
    }
} | Where-Object { $_.apply_record_id }

$total = $records.Count
Write-Host "找到 $total 个申请记录，开始串行执行完整流程..." -ForegroundColor Cyan

if (Test-Path $resultsLog) { Remove-Item $resultsLog }

$counter = 0
foreach ($record in $records) {
    $counter++
    $applyRecordId = $record.apply_record_id
    $email = $record.email
    $password = $record.password
    $url = $record.application_url
    
    Write-Host "`n========== [$counter/$total] 处理申请记录 ID: $applyRecordId ==========" -ForegroundColor Yellow
    
    $pipelineResult = [PSCustomObject]@{
        apply_record_id = $applyRecordId
        email = $email
        steps = @{}
        errors = @()
        success = $false
    }
    
    # 步骤1: 注册账号
    Write-Host "步骤1: 注册账号..." -ForegroundColor Cyan
    try {
        $registerBody = @{
            apply_record_id = $applyRecordId
            email = $email
            password = $password
            url = $url
            headless = $false
        } | ConvertTo-Json
        
        $registerRes = Invoke-RestMethod -Uri "$baseUrl/register" -Method Post -Headers $headers -Body $registerBody -TimeoutSec 300
        $pipelineResult.steps.register = $registerRes
        Write-Host "  注册结果: $($registerRes.status)" -ForegroundColor Green
    } catch {
        $err = "注册失败: $($_.Exception.Message)"
        Write-Host "  $err" -ForegroundColor Red
        $pipelineResult.errors += $err
        $pipelineResult.steps.register = @{ error = $_.Exception.Message }
    }
    
    Start-Sleep -Seconds 2
    
    # 步骤2: 启动流程
    Write-Host "步骤2: 启动流程..." -ForegroundColor Cyan
    try {
        $startBody = @{ apply_record_id = $applyRecordId } | ConvertTo-Json
        $startRes = Invoke-RestMethod -Uri "$baseUrl/start" -Method Post -Headers $headers -Body $startBody -TimeoutSec 60
        $pipelineResult.steps.start = $startRes
        Write-Host "  启动结果: $($startRes.status)" -ForegroundColor Green
    } catch {
        $err = "启动失败: $($_.Exception.Message)"
        Write-Host "  $err" -ForegroundColor Red
        $pipelineResult.errors += $err
        $pipelineResult.steps.start = @{ error = $_.Exception.Message }
    }
    
    Start-Sleep -Seconds 2
    
    # 步骤3: 执行分析
    Write-Host "步骤3: 执行分析..." -ForegroundColor Cyan
    try {
        $analyzeBody = @{ apply_record_id = $applyRecordId } | ConvertTo-Json
        $analyzeRes = Invoke-RestMethod -Uri "$baseUrl/analyze" -Method Post -Headers $headers -Body $analyzeBody -TimeoutSec 300
        $pipelineResult.steps.analyze = $analyzeRes
        Write-Host "  分析结果: $($analyzeRes.status), 缺失字段: $($analyzeRes.missing_count)" -ForegroundColor Green
    } catch {
        $err = "分析失败: $($_.Exception.Message)"
        Write-Host "  $err" -ForegroundColor Red
        $pipelineResult.errors += $err
        $pipelineResult.steps.analyze = @{ error = $_.Exception.Message }
        # 如果分析失败，跳过后续步骤
        $pipelineResultJson = ($pipelineResult | ConvertTo-Json -Depth 10 -Compress)
        Add-Content -Path $resultsLog -Value $pipelineResultJson
        continue
    }
    
    Start-Sleep -Seconds 2
    
    # 步骤4: 获取缺失字段
    Write-Host "步骤4: 获取缺失字段..." -ForegroundColor Cyan
    $missingFields = @()
    try {
        $missingRes = Invoke-RestMethod -Uri "$baseUrl/missing-fields/$applyRecordId" -Method Get -Headers $headers -TimeoutSec 60
        $missingFields = $missingRes.fields
        $pipelineResult.steps.missing_fields = @{
            count = $missingRes.count
            fields = $missingFields
        }
        Write-Host "  发现 $($missingRes.count) 个缺失字段" -ForegroundColor Green
    } catch {
        $err = "获取缺失字段失败: $($_.Exception.Message)"
        Write-Host "  $err" -ForegroundColor Red
        $pipelineResult.errors += $err
        $pipelineResult.steps.missing_fields = @{ error = $_.Exception.Message }
    }
    
    Start-Sleep -Seconds 1
    
    # 步骤5: 自动提交缺失字段（生成测试值）
    if ($missingFields.Count -gt 0) {
        Write-Host "步骤5: 自动提交缺失字段..." -ForegroundColor Cyan
        try {
            $fieldsToSubmit = @{}
            
            foreach ($field in $missingFields) {
                $fieldId = $field.field_id
                $fieldType = $field.field_type
                $fieldLabel = $field.field_label
                $options = $field.options
                
                # 根据字段类型和标签生成测试值
                $testValue = $null
                
                if ($options -and $options.Count -gt 0) {
                    # 如果有选项，选择第一个
                    $testValue = $options[0]
                } elseif ($fieldType -like "*select*" -or $fieldType -like "*dropdown*") {
                    $testValue = "Option 1"
                } elseif ($fieldLabel -match "(?i)(month|月份)") {
                    $testValue = "January"
                } elseif ($fieldLabel -match "(?i)(day|日期|天)") {
                    $testValue = "1"
                } elseif ($fieldLabel -match "(?i)(year|年份)") {
                    $testValue = "2024"
                } elseif ($fieldLabel -match "(?i)(phone|电话)") {
                    $testValue = "+1-555-0100"
                } elseif ($fieldLabel -match "(?i)(email|邮件)") {
                    $testValue = "test@example.com"
                } elseif ($fieldLabel -match "(?i)(address|地址)") {
                    $testValue = "123 Test Street"
                } elseif ($fieldLabel -match "(?i)(city|城市)") {
                    $testValue = "Test City"
                } elseif ($fieldLabel -match "(?i)(zip|postal|邮编)") {
                    $testValue = "12345"
                } elseif ($fieldType -like "*date*") {
                    $testValue = "2024-01-01"
                } elseif ($fieldType -like "*number*") {
                    $testValue = "1"
                } elseif ($fieldType -like "*email*") {
                    $testValue = "test@example.com"
                } else {
                    # 默认文本值
                    $testValue = "Test Value"
                }
                
                if ($testValue) {
                    $fieldsToSubmit[$fieldId] = $testValue
                }
            }
            
            if ($fieldsToSubmit.Count -gt 0) {
                $submitBody = @{
                    apply_record_id = $applyRecordId
                    fields = $fieldsToSubmit
                } | ConvertTo-Json -Depth 5
                
                $submitRes = Invoke-RestMethod -Uri "$baseUrl/submit-fields" -Method Post -Headers $headers -Body $submitBody -TimeoutSec 60
                $pipelineResult.steps.submit_fields = $submitRes
                Write-Host "  已提交 $($fieldsToSubmit.Count) 个字段值" -ForegroundColor Green
            } else {
                Write-Host "  没有可提交的字段值" -ForegroundColor Yellow
            }
        } catch {
            $err = "提交缺失字段失败: $($_.Exception.Message)"
            Write-Host "  $err" -ForegroundColor Red
            $pipelineResult.errors += $err
            $pipelineResult.steps.submit_fields = @{ error = $_.Exception.Message }
        }
        
        Start-Sleep -Seconds 2
    } else {
        Write-Host "步骤5: 无需提交缺失字段" -ForegroundColor Gray
    }
    
    # 步骤6: 执行表单填充
    Write-Host "步骤6: 执行表单填充..." -ForegroundColor Cyan
    try {
        $fillBody = @{
            apply_record_id = $applyRecordId
            headless = $false
        } | ConvertTo-Json
        
        $fillRes = Invoke-RestMethod -Uri "$baseUrl/fill" -Method Post -Headers $headers -Body $fillBody -TimeoutSec 600
        $pipelineResult.steps.fill = $fillRes
        Write-Host "  填充结果: 成功$($fillRes.filled), 失败$($fillRes.failed), 无值$($fillRes.no_value)" -ForegroundColor Green
    } catch {
        $err = "表单填充失败: $($_.Exception.Message)"
        Write-Host "  $err" -ForegroundColor Red
        $pipelineResult.errors += $err
        $pipelineResult.steps.fill = @{ error = $_.Exception.Message }
    }
    
    Start-Sleep -Seconds 2
    
    # 步骤7: 查看填充结果
    Write-Host "步骤7: 查看填充结果..." -ForegroundColor Cyan
    try {
        $fillResultRes = Invoke-RestMethod -Uri "$baseUrl/fill-result/$applyRecordId" -Method Get -Headers $headers -TimeoutSec 60
        $pipelineResult.steps.fill_result = $fillResultRes
        Write-Host "  填充详情已获取" -ForegroundColor Green
    } catch {
        $err = "获取填充结果失败: $($_.Exception.Message)"
        Write-Host "  $err" -ForegroundColor Red
        $pipelineResult.errors += $err
    }
    
    Start-Sleep -Seconds 1
    
    # 步骤8: 查看失败字段
    Write-Host "步骤8: 查看失败字段..." -ForegroundColor Cyan
    try {
        $failedRes = Invoke-RestMethod -Uri "$baseUrl/failed-fields/$applyRecordId" -Method Get -Headers $headers -TimeoutSec 60
        $pipelineResult.steps.failed_fields = $failedRes
        if ($failedRes.count -gt 0) {
            Write-Host "  发现 $($failedRes.count) 个失败字段" -ForegroundColor Yellow
        } else {
            Write-Host "  无失败字段" -ForegroundColor Green
        }
    } catch {
        $err = "获取失败字段失败: $($_.Exception.Message)"
        Write-Host "  $err" -ForegroundColor Red
        $pipelineResult.errors += $err
    }
    
    Start-Sleep -Seconds 1
    
    # 步骤9: 确认审核
    Write-Host "步骤9: 确认审核..." -ForegroundColor Cyan
    try {
        $reviewBody = @{
            apply_record_id = $applyRecordId
            action = "confirm"
        } | ConvertTo-Json
        
        $reviewRes = Invoke-RestMethod -Uri "$baseUrl/review" -Method Post -Headers $headers -Body $reviewBody -TimeoutSec 60
        $pipelineResult.steps.review = $reviewRes
        $pipelineResult.success = $true
        Write-Host "  审核确认完成" -ForegroundColor Green
    } catch {
        $err = "审核确认失败: $($_.Exception.Message)"
        Write-Host "  $err" -ForegroundColor Red
        $pipelineResult.errors += $err
        $pipelineResult.steps.review = @{ error = $_.Exception.Message }
    }
    
    # 保存结果
    $pipelineResultJson = ($pipelineResult | ConvertTo-Json -Depth 10 -Compress)
    Add-Content -Path $resultsLog -Value $pipelineResultJson
    
    Write-Host "完成记录 $applyRecordId，结果已保存" -ForegroundColor Green
    Start-Sleep -Seconds 1
}

Write-Host "`n========== 全部完成 ==========" -ForegroundColor Green
Write-Host "结果已保存到: $resultsLog" -ForegroundColor Cyan
Write-Host "共处理 $counter 条记录" -ForegroundColor Cyan

