# Extreme Wallpapers

macOS 브라우저 Extreme의 새 탭 배경 사진첩입니다. 모든 사진은 자유 이용 허가가 붙은 사진입니다.

## 구성

| 위치 | 내용 |
|------|------|
| `manifest.json` | 지금 사진첩에 있는 사진 목록. 앱이 하루에 한 번 읽습니다 |
| [`library` 릴리즈](../../releases/tag/library) | 위키미디어 공용 사진 파일 (가로 2560px JPEG) |
| [`archive` 릴리즈](../../releases/tag/archive) | 사진첩에서 뺀 사진을 날짜별 zip으로 보관. zip 안의 `credits.json`에 출처와 이용 허가 |
| `archive/index.json` | 보관한 사진 기록 (다시 들어오지 않게) |
| `curated.json` | 손으로 고른 사진. 위에서부터 차례로 들어갑니다 |
| `blocklist.json` | 넣지 않을 사진 |

## 갱신

[`Update wallpapers`](.github/workflows/update.yml)가 매주 월요일 09:00(한국 시간)에 돕니다. Actions 탭에서 바로 돌릴 수도 있습니다.

1. 위키미디어 공용 추천 사진(풍경, 산, 호수, 해안, 숲)에서 6장을 넣습니다. `curated.json`을 먼저 쓰고, 다 쓰면 최근 추천된 사진 중 가로 비율과 크기, 이용 허가가 맞는 것을 고릅니다.
2. 저장소 비밀 값 `UNSPLASH_ACCESS_KEY`가 있으면 Unsplash "Wallpapers"·"Nature" 주제에서 사진 설명에 풍경 단어(산, 바다, 숲, 하늘 등)가 있는 사진 2장을 더 넣습니다. Unsplash API 규칙대로 Unsplash 사진은 Unsplash 주소에서 바로 받고, 넣을 때 다운로드 알림을 보냅니다.
3. 사진이 60장을 넘거나 120일이 지난 사진(최소 24장은 남김)은 zip으로 묶어 `archive` 릴리즈에 올리고 목록에서 뺍니다.

마음에 들지 않는 사진은 `blocklist.json`에 위키미디어 파일 제목(`File:...`)이나 `us-<Unsplash 사진 ID>`를 넣으면 다음 갱신 때 빠집니다(이미 사진첩에 있어도 빠짐).
바로 빼려면 Actions 탭에서 `Update wallpapers`를 "새 사진 넣기"를 끄고 돌리면 됩니다.

## 출처와 이용 허가

각 사진의 작가, 이용 허가, 원본 페이지는 `manifest.json`의 `author`, `license`, `licenseUrl`, `page`에 있습니다.

- 위키미디어 공용 사진: 대부분 CC BY-SA. 원본을 가로 2560px로 줄인 것 외에는 바꾸지 않았습니다.
- Unsplash 사진: [Unsplash License](https://unsplash.com/license)
