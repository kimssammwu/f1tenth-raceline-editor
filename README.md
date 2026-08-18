# F1TENTH Raceline Editor — uv standalone

`ssupath-f1tenth-race-stack`의 global raceline 생성부와 맵/섹터 편집기를 ROS2 launch 없이 실행하기 위한 독립 프로젝트입니다.

## 설치

```bash
uv sync
uv run raceline bootstrap
uv run raceline doctor
```

`.python-version`은 Python 3.10으로 고정되어 있습니다. optimizer/config는 upstream commit `acbf008694eef416ed1b189779da2b8f26996909`에 고정됩니다.

## 레이스라인 생성

```bash
uv run raceline generate --map maps/teras/teras.yaml
```

맵 편집 프로필을 적용하려면:

```bash
uv run raceline generate \
  --map maps/teras/teras.yaml \
  --edit maps/teras/edit/map_edit.json
```

기본 생성 결과는 `<map-dir>/output/`에 모입니다.

```text
output/
├── centerline.csv
├── raceline_iqp.csv
├── raceline_shortest.csv
├── ltpl.csv
├── bound_left.csv
├── bound_right.csv
├── global_waypoints.json
├── ltpl_waypoints.json
├── summary.json
├── speed_scaling.yaml      # 섹터 저장 후
└── ot_sectors.yaml         # 섹터 저장 후
```

`global_waypoints.json`과 `ltpl_waypoints.json`은 원본 ROS stack의 waypoint message 직렬화 구조와 호환되도록 생성합니다.

## 로컬 브라우저 편집기

```bash
uv run raceline edit --map maps/teras/teras.yaml
```

편집기에서 다음을 처리합니다.

- 비파괴 occupancy map brush 편집
- 편집된 맵 기준 centerline preview
- 레이스라인 재생성
- Speed sector 편집
- Overtaking sector 편집
- ROS 호환 sector YAML export

맵 편집 원본은 `<map-dir>/edit/map_edit.json`, 섹터 canonical source는 `<map-dir>/edit/sectors.json`에 저장합니다. 생성 결과와 sector YAML은 `<map-dir>/output/`에 저장합니다.

## 온라인 서비스

```bash
uv run raceline edit \
  --online-service \
  --host 0.0.0.0 \
  --port 8765 \
  --no-browser
```

브라우저에서 맵 YAML과 해당 YAML의 `image:`가 참조하는 PNG/PGM/JPG 이미지를 함께 드래그 앤 드롭합니다. 업로드 단계에서 다음을 검사합니다.

- `image`, `resolution`, `origin`을 갖는 맵 YAML이 정확히 하나인지
- `resolution > 0`이고 `origin`이 숫자 `[x, y, yaw]`인지
- YAML이 참조하는 이미지가 함께 업로드되었는지
- 이미지가 실제로 OpenCV에서 디코딩 가능한지
- 중복 파일명, 경로가 포함된 파일명, 허용되지 않은 확장자가 없는지
- 내부 편집기 서버가 실제로 기동했는지

보조 YAML 파일은 업로드할 수 있지만 맵 YAML로 오인하지 않습니다. 온라인 프로젝트 편집기는 `/editor/<project-id>/` 아래로 격리되므로 reverse proxy 환경에서도 내부 `127.0.0.1:<port>`가 브라우저에 노출되지 않습니다. 프로젝트 다운로드는 ZIP으로 제공되며 `.work` 진단 임시파일은 제외합니다.

예를 들어 `f1tenth.example.com`을 사용할 경우 reverse proxy는 온라인 서비스 포트 전체를 해당 도메인으로 전달하면 됩니다.

## 섹터 편집

레이스라인을 먼저 생성한 뒤 `속도 섹터` / `추월 섹터` 탭을 사용합니다. 내부 canonical representation은 waypoint index가 아니라 물리 거리 `s_m`입니다. raceline point density가 바뀌어도 split 위치를 최대한 유지하고, ROS YAML export 시 현재 raceline의 nearest waypoint index로 변환합니다.

GUI 없이 sector YAML을 다시 export할 수도 있습니다.

```bash
uv run raceline sectors --map maps/teras/teras.yaml
```

검증 항목에는 `only_FTG`/`no_FTG` 충돌, global speed limit 초과, 너무 짧은 speed/OT sector, stale raceline, shortest-path 누락 등이 포함됩니다.

## 최적화 실패 진단

`mincurv_iqp`가 실패하면 실패 iteration의 reftrack을 `<output>/.work/` 아래 CSV로 기록합니다. 동일 safety width의 `mincurv` fallback은 차량 곡률 제한을 완화하지 않고 검증합니다. optimizer가 반환한 kappa 열만 비정상인 경우에도 XY geometry에서 독립 계산한 곡률이 실제 제한을 만족할 때만 복구합니다. 이 검증은 CLI, 로컬 GUI, 온라인 GUI에 동일하게 적용됩니다.

폐곡선 centerline은 periodic Savitzky-Golay smoothing과 periodic cubic spline resampling을 사용하여 contour 시작점의 seam 때문에 인위적인 곡률 spike가 생기지 않도록 처리합니다.

## Tests

```bash
uv run pytest -q
```

테스트는 output contract, 원본 waypoint JSON schema, periodic centerline seam, optimizer fallback validation, map edit, sector schema/validation, 온라인 upload/proxy 경로와 binary multipart 보존을 포함합니다. GitHub Actions에서도 PR마다 같은 pytest suite를 실행합니다.
