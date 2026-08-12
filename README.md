# F1TENTH Raceline Offline — uv standalone

`ssupath-f1tenth-race-stack`의 global raceline 생성부를 ROS2 launch 없이 실행하기 위한
독립 프로젝트입니다.

## 목표

새 PC에 필요한 것은 다음뿐입니다.

- `uv`
- `git`
- 인터넷 연결 (첫 설치/첫 bootstrap 때만)
- 생성할 맵의 `.yaml` + `.png`

ROS2, colcon workspace, `f110_msgs`, RViz, F1TENTH Gym은 필요하지 않습니다.

이 프로젝트는 upstream 코드를 임의로 최신화하지 않습니다.
`hee4040/ssupath-f1tenth-race-stack`의 아래 커밋을 sparse checkout하여 사용합니다.

```text
acbf008694eef416ed1b189779da2b8f26996909
```

따라서 다른 PC에서도 같은 optimizer 코드를 가져오도록 고정되어 있습니다.

## Dependency baseline

이 프로젝트는 `trajectory-planning-helpers==0.80`을 사용합니다.
고정된 ssupath optimizer가 `iqp_handler()`에 `spline_len`, `psi`, `kappa`, `dkappa`를
전달하는 최신 IQP API를 사용하기 때문입니다. TPH 0.76으로는 해당 호출이 동작하지 않습니다.

`quadprog==0.1.13`을 직접 고정하며, TPH 0.80의 `quadprog~=0.1.11` 제약과 호환됩니다.
또한 TPH upstream의 `spline_approximation.dist_to_p()`가 최신 SciPy에서 1-D vector 오류를
일으키는 문제를 피하기 위해, spline parameter를 scalar로 정규화하는 좁은 런타임 호환 패치를
적용합니다. 이 패치는 optimizer 수식, 파라미터, 출력 파일 형식을 변경하지 않습니다.

## 1. uv 설치

Linux/macOS:

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh
```

Windows PowerShell:

```powershell
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
```

## 2. 프로젝트 세팅

Linux/macOS:

```bash
chmod +x setup.sh
./setup.sh
```

Windows:

```powershell
.\setup.ps1
```

수동으로 하면:

```bash
uv sync
uv run raceline bootstrap
uv run raceline doctor
```

`.python-version`이 `3.10`이므로 uv가 Python 3.10 환경을 사용합니다.

`bootstrap`은 전체 race stack을 checkout하지 않고 다음 두 경로만 sparse checkout 합니다.

```text
planner/global_planner/global_planner/global_racetrajectory_optimization
stack_master/config/global_planner
```

## 3. 맵 준비

```text
maps/
└── teras/
    ├── teras.yaml
    └── teras.png
```

## 4. 맵 편집

```bash
uv run raceline edit --map maps/teras/teras.yaml
```

브라우저에서 free-space / occupied-space brush, undo/redo, centerline preview를 사용할 수 있습니다.
편집 내용은 원본 PNG를 덮어쓰지 않고 `map_edit.json`에 저장됩니다.

## 5. 레이스라인 생성

원본 맵:

```bash
uv run raceline generate --map maps/teras/teras.yaml
```

편집 프로필 적용:

```bash
uv run raceline generate \
  --map maps/teras/teras.yaml \
  --edit maps/teras/edit/map_edit.json
```

기본 설정은 원래 ROS 설정과 동일합니다.

```text
safety_width    = 0.4 m
safety_width_sp = 0.35 m
```

반대 방향:

```bash
uv run raceline generate --map maps/teras/teras.yaml --reverse
```

방향 기준 pose 명시:

```bash
uv run raceline generate \
  --map maps/teras/teras.yaml \
  --initial-pose 1.2 -0.4 1.57
```

## 출력

기본적으로 `<map-dir>/raceline_offline/`에 기존 contract와 동일한 파일을 생성합니다.

```text
centerline.csv
raceline_iqp.csv
raceline_shortest.csv
ltpl.csv
bound_left.csv
bound_right.csv
summary.json
.work/
```

`raceline_iqp.csv` 형식:

```text
s_m,x_m,y_m,psi_rad,kappa_radpm,vx_mps,ax_mps2
```

## 문제 확인

```bash
uv run raceline doctor
```

다음을 확인합니다.

- Python / Git
- NumPy / SciPy / OpenCV / scikit-image
- CasADi / scikit-learn
- quadprog
- trajectory-planning-helpers
- pinned ssupath source
- TPH/SciPy spline compatibility shim

### `ValueError: Input vector should be 1-D.`

TPH 0.80의 `spline_approximation.dist_to_p()`와 최신 SciPy 사이 shape 호환 문제입니다.
v0.2.2는 spline parameter를 scalar로 정규화하는 좁은 런타임 패치를 포함합니다.

정상이면 doctor에 다음이 표시됩니다.

```text
TPH/SciPy spline compatibility: OK
```

## 출력 호환성

맵 편집 기능은 기존 planner core 앞단에만 추가되어 있습니다.

- `--edit` 없음: 기존 계산 경로 사용
- empty edit: 원본 occupancy image와 pixel-equivalent 입력
- 실제 edit: trajectory 수치는 바뀔 수 있지만 파일명/CSV schema/JSON schema/default optimizer 설정은 유지

자세한 내용은 `COMPATIBILITY.md`를 참고하세요.
