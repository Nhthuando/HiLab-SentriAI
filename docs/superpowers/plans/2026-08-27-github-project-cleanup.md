# HiLab-SentriAI GitHub Project Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Giảm workspace HiLab-SentriAI từ khoảng 18,7 GB xuống khoảng 300–500 MB, bảo toàn dữ liệu train trong archive ngoài repository và đưa đúng bundle V9 production vào Git.

**Architecture:** Thực hiện tuần tự theo ba lớp: chốt baseline bất biến, move dữ liệu lớn sang archive có manifest kiểm chứng, rồi mới xóa dependency/cache có thể tái tạo. Bundle V9 production luôn ở nguyên đường dẫn runtime và được cho phép theo dõi riêng qua `.gitignore`; mọi dataset, run và export khác tiếp tục bị ignore.

**Tech Stack:** PowerShell 7/Windows PowerShell, Git, Node.js/npm, Python/pytest, Ultralytics YOLO artifact, JSON manifest.

## Global Constraints

- Archive bắt buộc đặt tại `D:\HuuThuan - Project\HiLab-SentriAI-training-archive\2026-08-27`.
- Không retrain, convert, quantize hoặc sửa model V9.
- SHA-256 bắt buộc của `best.pt` là `3772E978FC4635A6A2D3DFFB59286BD89C0EBBC6CC6E27DC77532B5006EAAB52` trước và sau cleanup.
- Không thay confidence, image size, tracker, Zone logic, pipeline inference, database record hoặc CVAT Docker volume.
- Không xóa source, test, docs, Prisma schema/migration, package manifest, lockfile, cấu hình mẫu, model nền hoặc `.local/cvat/`.
- Mọi recursive move/delete phải resolve đường dẫn tuyệt đối và xác minh nằm trong workspace hoặc archive đã chỉ định trước khi thực hiện.
- Chạy tuần tự từng tác vụ; không quét hoặc copy nhiều nhóm lớn song song.

---

## File Map

- Modify: `.gitignore` — tiếp tục chặn mọi training artifact ngoại trừ bundle V9 production.
- Track: `backend/data/training/models/baikiem-v9-unified-candidate-final/best.pt` — checkpoint runtime chính thức.
- Track: `backend/data/training/models/baikiem-v9-unified-candidate-final/labels.json` — class map runtime.
- Track: `backend/data/training/models/baikiem-v9-unified-candidate-final/evaluation.json` — metadata đánh giá và approval.
- Track: `backend/data/training/models/baikiem-v9-unified-candidate-final/training-receipt.json` — provenance của lần train.
- Create outside repository: `D:\HuuThuan - Project\HiLab-SentriAI-training-archive\2026-08-27\manifest.json` — inventory, vị trí khôi phục và trạng thái kiểm chứng.
- Move outside repository: các nội dung cũ của `backend/data/training/` ngoại trừ bundle V9 production, cùng `backend/data/external-datasets/` và `backend/data/evaluation/`.
- Delete locally: `.venv`, `node_modules`, `dist`, `__pycache__`, `.pytest_cache` và Vite cache đã xác minh.

### Task 1: Baseline và cổng bất biến V9

**Files:**
- Read: `backend/data/training/models/baikiem-v9-unified-candidate-final/best.pt`
- Read: `backend/data/training/models/baikiem-v9-unified-candidate-final/labels.json`
- Read: `backend/data/training/models/baikiem-v9-unified-candidate-final/evaluation.json`
- Read: `backend/data/training/models/baikiem-v9-unified-candidate-final/training-receipt.json`
- Read: `backend/.env`
- Read: `.gitignore`

**Interfaces:**
- Consumes: workspace hiện tại và bundle V9 production.
- Produces: hash, file count, byte count và baseline test dùng làm cổng cho các task sau.

- [ ] **Step 1: Xác minh workspace và archive target**

Run:

```powershell
$workspace = (Resolve-Path -LiteralPath 'D:\HuuThuan - Project\HiLab-SentriAI').Path.TrimEnd('\')
$archiveRoot = [IO.Path]::GetFullPath('D:\HuuThuan - Project\HiLab-SentriAI-training-archive\2026-08-27').TrimEnd('\')
if ($archiveRoot.StartsWith($workspace + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Archive must be outside workspace' }
if (Test-Path -LiteralPath $archiveRoot) { throw "Archive target already exists: $archiveRoot" }
"WORKSPACE=$workspace"
"ARCHIVE=$archiveRoot"
```

Expected: hai đường dẫn tuyệt đối được in ra và archive chưa tồn tại.

- [ ] **Step 2: Xác minh V9 production đủ bốn file và đúng hash**

Run:

```powershell
$modelDir = 'D:\HuuThuan - Project\HiLab-SentriAI\backend\data\training\models\baikiem-v9-unified-candidate-final'
$required = @('best.pt', 'labels.json', 'evaluation.json', 'training-receipt.json')
foreach ($name in $required) {
    $path = Join-Path $modelDir $name
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing production artifact: $path" }
}
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $modelDir 'best.pt')).Hash
if ($hash -ne '3772E978FC4635A6A2D3DFFB59286BD89C0EBBC6CC6E27DC77532B5006EAAB52') { throw "Unexpected V9 hash: $hash" }
$required | ForEach-Object { Get-Item -LiteralPath (Join-Path $modelDir $_) } | Select-Object Name,Length
```

Expected: bốn artifact tồn tại; hash không phát sinh exception.

- [ ] **Step 3: Chạy smoke test trước cleanup khi dependency còn sẵn**

Run:

```powershell
npm run typecheck
npm run build
```

Working directory: `backend/node-api`.

Expected: TypeScript typecheck và build đều exit code 0.

Run:

```powershell
npm run build
```

Working directory: `frontend`.

Expected: Vite build exit code 0.

Run:

```powershell
.\.venv\Scripts\python.exe -m pytest tests/test_activate_v9_production.py tests/test_area_pipeline.py -q
```

Working directory: `backend/python-worker`.

Expected: selected production/pipeline tests pass. Ghi rõ mọi baseline failure có sẵn; không được quy lỗi cho cleanup.

- [ ] **Step 4: Ghi số liệu baseline để đối chiếu trong manifest**

Run:

```powershell
$roots = @(
    'backend\data\training',
    'backend\data\external-datasets',
    'backend\data\evaluation',
    'backend\python-worker\.venv',
    'backend\node-api\node_modules',
    'frontend\node_modules'
)
foreach ($relative in $roots) {
    $path = Join-Path 'D:\HuuThuan - Project\HiLab-SentriAI' $relative
    $measure = Get-ChildItem -LiteralPath $path -File -Recurse -Force -ErrorAction Stop | Measure-Object Length -Sum
    [pscustomobject]@{ Path = $relative; Files = $measure.Count; Bytes = [int64]$measure.Sum }
}
```

Expected: có file count và byte count cho cả sáu nhóm.

### Task 2: Di chuyển dữ liệu train sang archive có kiểm chứng

**Files:**
- Create: `D:\HuuThuan - Project\HiLab-SentriAI-training-archive\2026-08-27\manifest.json`
- Move: `backend/data/training/*` ngoại trừ `models/baikiem-v9-unified-candidate-final/`
- Move: `backend/data/external-datasets/`
- Move: `backend/data/evaluation/`

**Interfaces:**
- Consumes: baseline Task 1 và archive target chưa tồn tại.
- Produces: archive giữ nguyên cấu trúc tương đối, manifest `schemaVersion: 1`, `status: VERIFIED`, và repository chỉ còn bundle V9 trong training data.

- [ ] **Step 1: Dừng riêng service chạy từ workspace để tránh file lock**

Run:

```powershell
$workspace = 'D:\HuuThuan - Project\HiLab-SentriAI'
$ports = @(3001, 5173, 8001)
$owners = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue |
    Where-Object { $_.LocalPort -in $ports } |
    Select-Object -ExpandProperty OwningProcess -Unique
foreach ($pidValue in $owners) {
    $process = Get-CimInstance Win32_Process -Filter "ProcessId=$pidValue"
    if ($process.CommandLine -and $process.CommandLine.IndexOf($workspace, [StringComparison]::OrdinalIgnoreCase) -ge 0) {
        Stop-Process -Id $pidValue -Force
    }
}
```

Expected: chỉ Node/Python process có command line chứa đúng workspace và giữ các port 3001, 5173 hoặc 8001 bị dừng; Docker/CVAT không bị dừng.

- [ ] **Step 2: Tạo archive root và danh sách nguồn đã validate**

Run trong một PowerShell session:

```powershell
$workspace = [IO.Path]::GetFullPath('D:\HuuThuan - Project\HiLab-SentriAI').TrimEnd('\')
$archiveRoot = [IO.Path]::GetFullPath('D:\HuuThuan - Project\HiLab-SentriAI-training-archive\2026-08-27').TrimEnd('\')
$trainingRoot = Join-Path $workspace 'backend\data\training'
$modelsRoot = Join-Path $trainingRoot 'models'
$protectedModel = Join-Path $modelsRoot 'baikiem-v9-unified-candidate-final'

function Assert-Under([string]$Parent, [string]$Candidate) {
    $parentFull = [IO.Path]::GetFullPath($Parent).TrimEnd('\') + '\'
    $candidateFull = [IO.Path]::GetFullPath($Candidate)
    if (-not $candidateFull.StartsWith($parentFull, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe path outside $Parent`: $Candidate"
    }
}

if (Test-Path -LiteralPath $archiveRoot) { throw "Archive target already exists: $archiveRoot" }
New-Item -ItemType Directory -Path $archiveRoot | Out-Null

$moveSources = @()
$moveSources += Get-ChildItem -LiteralPath $trainingRoot -Force |
    Where-Object { $_.FullName -ne $modelsRoot }
$moveSources += Get-ChildItem -LiteralPath $modelsRoot -Force |
    Where-Object { $_.FullName -ne $protectedModel }
$moveSources += Get-Item -LiteralPath (Join-Path $workspace 'backend\data\external-datasets')
$moveSources += Get-Item -LiteralPath (Join-Path $workspace 'backend\data\evaluation')

foreach ($source in $moveSources) {
    Assert-Under $workspace $source.FullName
    $relative = $source.FullName.Substring($workspace.Length).TrimStart('\')
    $destination = Join-Path $archiveRoot $relative
    Assert-Under $archiveRoot $destination
    [pscustomobject]@{ Source = $source.FullName; Destination = $destination }
}
```

Expected: danh sách chỉ chứa training artifact cũ, external dataset và evaluation; không chứa bundle `baikiem-v9-unified-candidate-final`.

- [ ] **Step 3: Chụp inventory, move tuần tự và kiểm chứng từng item**

Tiếp tục trong cùng PowerShell session của Step 2:

```powershell
function Get-TreeStat([string]$Path) {
    if (Test-Path -LiteralPath $Path -PathType Leaf) {
        $file = Get-Item -LiteralPath $Path
        return [pscustomobject]@{ Files = 1; Bytes = [int64]$file.Length }
    }
    $measure = Get-ChildItem -LiteralPath $Path -File -Recurse -Force -ErrorAction Stop |
        Measure-Object Length -Sum
    return [pscustomobject]@{ Files = [int64]$measure.Count; Bytes = [int64]$measure.Sum }
}

$manifestItems = @()
foreach ($source in $moveSources) {
    $relative = $source.FullName.Substring($workspace.Length).TrimStart('\')
    $destination = Join-Path $archiveRoot $relative
    $before = Get-TreeStat $source.FullName
    $destinationParent = Split-Path -Parent $destination
    New-Item -ItemType Directory -Path $destinationParent -Force | Out-Null
    Move-Item -LiteralPath $source.FullName -Destination $destination -ErrorAction Stop
    $after = Get-TreeStat $destination
    if ($before.Files -ne $after.Files -or $before.Bytes -ne $after.Bytes) {
        throw "Archive verification failed for $relative"
    }
    $manifestItems += [pscustomobject]@{
        relativePath = $relative
        sourcePath = $source.FullName
        archivePath = $destination
        files = $after.Files
        bytes = $after.Bytes
        verified = $true
    }
}
```

Expected: mỗi item chỉ được xử lý sau khi item trước đã move và verify xong.

- [ ] **Step 4: Ghi manifest VERIFIED và xác minh V9 vẫn ở nguyên vị trí**

Tiếp tục trong cùng PowerShell session:

```powershell
$v9Path = Join-Path $protectedModel 'best.pt'
$v9Hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $v9Path).Hash
if ($v9Hash -ne '3772E978FC4635A6A2D3DFFB59286BD89C0EBBC6CC6E27DC77532B5006EAAB52') {
    throw "V9 changed during archive: $v9Hash"
}
$manifest = [ordered]@{
    schemaVersion = 1
    status = 'VERIFIED'
    createdAt = (Get-Date).ToString('o')
    sourceWorkspace = $workspace
    archiveRoot = $archiveRoot
    productionModel = [ordered]@{ relativePath = 'backend\data\training\models\baikiem-v9-unified-candidate-final\best.pt'; sha256 = $v9Hash }
    items = $manifestItems
    totalFiles = [int64](($manifestItems | Measure-Object files -Sum).Sum)
    totalBytes = [int64](($manifestItems | Measure-Object bytes -Sum).Sum)
}
$manifestPath = Join-Path $archiveRoot 'manifest.json'
$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding UTF8
Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json | Select-Object schemaVersion,status,totalFiles,totalBytes
```

Expected: `schemaVersion=1`, `status=VERIFIED`, và hash V9 đúng giá trị bắt buộc.

### Task 3: Đưa bundle V9 production vào Git mà không lộ dữ liệu lớn

**Files:**
- Modify: `.gitignore`
- Track: `backend/data/training/models/baikiem-v9-unified-candidate-final/best.pt`
- Track: `backend/data/training/models/baikiem-v9-unified-candidate-final/labels.json`
- Track: `backend/data/training/models/baikiem-v9-unified-candidate-final/evaluation.json`
- Track: `backend/data/training/models/baikiem-v9-unified-candidate-final/training-receipt.json`

**Interfaces:**
- Consumes: repository sau Task 2 chỉ còn bundle V9 trong training tree.
- Produces: GitHub clone có đúng V9 production; các training artifact khác vẫn bị ignore.

- [ ] **Step 1: Thêm exception hẹp ở cuối `.gitignore`**

Append chính xác các rule sau bằng `apply_patch`:

```gitignore

# Production V9 runtime bundle required by GitHub clones
!backend/data/training/
backend/data/training/*
!backend/data/training/models/
backend/data/training/models/*
!backend/data/training/models/baikiem-v9-unified-candidate-final/
!backend/data/training/models/baikiem-v9-unified-candidate-final/best.pt
!backend/data/training/models/baikiem-v9-unified-candidate-final/labels.json
!backend/data/training/models/baikiem-v9-unified-candidate-final/evaluation.json
!backend/data/training/models/baikiem-v9-unified-candidate-final/training-receipt.json
```

Expected: rule cuối cùng override cả `backend/data/training/` và `*.pt` nhưng chỉ cho phép đúng một bundle.

- [ ] **Step 2: Kiểm tra ignore policy trước khi stage**

Run:

```powershell
git check-ignore -v backend/data/training/models/baikiem-v9-unified-candidate-final/best.pt
git status --short --untracked-files=all
```

Expected: `git check-ignore` exit code 1 vì V9 không còn bị ignore. `git status` chỉ thêm `.gitignore` và bốn file bundle V9; không có dataset, CVAT ZIP, video, `.env`, cache hoặc model cũ.

- [ ] **Step 3: Chặn file GitHub quá lớn và kiểm tra secret theo tên**

Run:

```powershell
$allowedRoot = 'backend/data/training/models/baikiem-v9-unified-candidate-final/'
$pending = git ls-files --others --exclude-standard
foreach ($path in $pending) {
    $item = Get-Item -LiteralPath $path
    if ($item.Length -ge 95MB) { throw "Pending file too large for GitHub: $path" }
    if ($path -match '(^|/)(\.env|.*\.env\..*)$') { throw "Secret-like file is pending: $path" }
    if ($path.StartsWith('backend/data/training/', [StringComparison]::OrdinalIgnoreCase) -and -not $path.StartsWith($allowedRoot, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unexpected training artifact is pending: $path"
    }
}
$pending
```

Expected: chỉ bốn file V9 production là untracked data artifact.

- [ ] **Step 4: Stage và commit GitHub runtime bundle**

Run:

```powershell
git add -- .gitignore backend/data/training/models/baikiem-v9-unified-candidate-final/best.pt backend/data/training/models/baikiem-v9-unified-candidate-final/labels.json backend/data/training/models/baikiem-v9-unified-candidate-final/evaluation.json backend/data/training/models/baikiem-v9-unified-candidate-final/training-receipt.json
git diff --cached --stat
git commit -m "build: package V9 runtime model"
```

Expected: commit chỉ gồm `.gitignore` và bốn artifact V9.

### Task 4: Xóa dependency, build và cache có thể tái tạo

**Files:**
- Delete: `backend/python-worker/.venv/`
- Delete: `backend/node-api/node_modules/`
- Delete: `frontend/node_modules/`
- Delete: `backend/node-api/dist/`
- Delete: `frontend/dist/`
- Delete: mọi `__pycache__/`, `.pytest_cache/` và cache Vite dưới workspace.
- Preserve: `backend/python-worker/requirements.txt`
- Preserve: `backend/node-api/package.json`
- Preserve: `backend/node-api/package-lock.json`
- Preserve: `frontend/package.json`
- Preserve: `frontend/package-lock.json`

**Interfaces:**
- Consumes: baseline test đã chạy và archive VERIFIED.
- Produces: workspace nhẹ, dependency có thể tái tạo chính xác từ manifest/lockfile.

- [ ] **Step 1: Xác minh archive VERIFIED trước khi xóa**

Run:

```powershell
$manifestPath = 'D:\HuuThuan - Project\HiLab-SentriAI-training-archive\2026-08-27\manifest.json'
$manifest = Get-Content -Raw -LiteralPath $manifestPath | ConvertFrom-Json
if ($manifest.status -ne 'VERIFIED' -or $manifest.totalFiles -le 0 -or $manifest.totalBytes -le 0) {
    throw 'Archive manifest is not VERIFIED'
}
$manifest | Select-Object status,totalFiles,totalBytes
```

Expected: manifest có trạng thái `VERIFIED` và thống kê lớn hơn 0.

- [ ] **Step 2: Resolve và validate mọi target xóa**

Run trong một PowerShell session:

```powershell
$workspace = [IO.Path]::GetFullPath('D:\HuuThuan - Project\HiLab-SentriAI').TrimEnd('\')
function Assert-WorkspaceChild([string]$Candidate) {
    $candidateFull = [IO.Path]::GetFullPath($Candidate)
    if (-not $candidateFull.StartsWith($workspace + '\', [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe delete target: $candidateFull"
    }
    if ($candidateFull -eq $workspace) { throw 'Workspace root cannot be deleted' }
    return $candidateFull
}

$fixedTargets = @(
    'backend\python-worker\.venv',
    'backend\node-api\node_modules',
    'frontend\node_modules',
    'backend\node-api\dist',
    'frontend\dist'
)
$deleteTargets = @()
foreach ($relative in $fixedTargets) {
    $candidate = Join-Path $workspace $relative
    if (Test-Path -LiteralPath $candidate) { $deleteTargets += Assert-WorkspaceChild $candidate }
}
$cacheTargets = Get-ChildItem -LiteralPath $workspace -Directory -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Name -in @('__pycache__', '.pytest_cache', '.vite', '.vite-temp') }
foreach ($cache in $cacheTargets) { $deleteTargets += Assert-WorkspaceChild $cache.FullName }
$deleteTargets | Sort-Object -Unique
```

Expected: danh sách không chứa workspace root, source, archive, `.git`, `.local/cvat`, model V9 hoặc model nền.

- [ ] **Step 3: Xóa tuần tự đúng target đã xác minh**

Tiếp tục trong cùng PowerShell session của Step 2:

```powershell
foreach ($target in ($deleteTargets | Sort-Object Length -Descending -Unique)) {
    if (Test-Path -LiteralPath $target) {
        Remove-Item -LiteralPath $target -Recurse -Force -ErrorAction Stop
        if (Test-Path -LiteralPath $target) { throw "Delete did not complete: $target" }
    }
}
```

Expected: mỗi target bị xóa hoàn toàn; không dùng wildcard hoặc đường dẫn ngoài workspace.

- [ ] **Step 4: Xác minh dependency manifests còn nguyên**

Run:

```powershell
$required = @(
    'backend\python-worker\requirements.txt',
    'backend\node-api\package.json',
    'backend\node-api\package-lock.json',
    'frontend\package.json',
    'frontend\package-lock.json'
)
foreach ($relative in $required) {
    $path = Join-Path 'D:\HuuThuan - Project\HiLab-SentriAI' $relative
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing dependency manifest: $relative" }
}
$required
```

Expected: cả năm manifest/lockfile còn tồn tại.

### Task 5: Kiểm tra GitHub hygiene, dung lượng và khả năng khôi phục

**Files:**
- Verify: `.gitignore`
- Verify: `backend/data/training/models/baikiem-v9-unified-candidate-final/*`
- Verify outside repository: `D:\HuuThuan - Project\HiLab-SentriAI-training-archive\2026-08-27\manifest.json`

**Interfaces:**
- Consumes: repository đã archive, package V9 và dọn dependency.
- Produces: báo cáo cuối gồm dung lượng workspace, archive, hash V9, Git status và lệnh phục hồi.

- [ ] **Step 1: Xác minh V9 sau toàn bộ cleanup**

Run:

```powershell
$best = 'D:\HuuThuan - Project\HiLab-SentriAI\backend\data\training\models\baikiem-v9-unified-candidate-final\best.pt'
$hash = (Get-FileHash -Algorithm SHA256 -LiteralPath $best).Hash
if ($hash -ne '3772E978FC4635A6A2D3DFFB59286BD89C0EBBC6CC6E27DC77532B5006EAAB52') { throw "V9 hash changed: $hash" }
Get-ChildItem -LiteralPath (Split-Path -Parent $best) -File | Select-Object Name,Length
```

Expected: bốn file production còn nguyên và hash đúng.

- [ ] **Step 2: Xác minh Git chỉ chứa source và bundle V9 cho phép**

Run:

```powershell
git status --short --untracked-files=all
git ls-files backend/data/training
git ls-files | ForEach-Object {
    if (Test-Path -LiteralPath $_ -PathType Leaf) {
        $file = Get-Item -LiteralPath $_
        if ($file.Length -ge 95MB) { [pscustomobject]@{ Path = $_; Bytes = $file.Length } }
    }
}
```

Expected: worktree sạch; `git ls-files backend/data/training` trả đúng bốn file V9; không có tracked file từ 95 MB trở lên.

- [ ] **Step 3: Đo dung lượng cuối và archive**

Run:

```powershell
$workspace = 'D:\HuuThuan - Project\HiLab-SentriAI'
$archive = 'D:\HuuThuan - Project\HiLab-SentriAI-training-archive\2026-08-27'
foreach ($path in @($workspace, $archive)) {
    $measure = Get-ChildItem -LiteralPath $path -File -Recurse -Force -ErrorAction Stop | Measure-Object Length -Sum
    [pscustomobject]@{ Path = $path; Files = $measure.Count; GB = [math]::Round($measure.Sum / 1GB, 3) }
}
```

Expected: workspace khoảng 300–500 MB; archive khoảng 12,9 GB. Sai số nhỏ được chấp nhận do filesystem metadata và build output đã có trước đó.

- [ ] **Step 4: Xác minh đường phục hồi không cần chạy cài đặt ngay**

Run:

```powershell
npm ci --dry-run --ignore-scripts
```

Working directory: `backend/node-api` rồi `frontend`, tuần tự.

Expected: lockfile hợp lệ. Nếu npm cần network và thất bại vì offline, ghi nhận là giới hạn môi trường; không tạo lại `node_modules` trong cleanup turn.

Python restore command cần báo lại cho người dùng, không chạy để tránh tái tạo 5,32 GB ngay:

```powershell
py -m venv backend\python-worker\.venv
backend\python-worker\.venv\Scripts\python.exe -m pip install -r backend\python-worker\requirements.txt
```

- [ ] **Step 5: Báo cáo kết quả**

Báo cáo chính xác:

- Workspace trước/sau cleanup.
- Tổng file và byte đã chuyển vào archive.
- Tổng dung lượng dependency/cache đã xóa.
- Archive path và `manifest.json`.
- SHA-256 V9 trước/sau.
- Commit chứa bundle V9.
- Dịch vụ 3001/5173/8001 đã dừng và cần người dùng chạy lại sau khi cài dependency.
- Các lệnh khôi phục dependency và dữ liệu train.
