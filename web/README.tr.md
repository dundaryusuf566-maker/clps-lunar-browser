# Arayüz (React + Vite)

*English: [README.md](README.md). Bu Türkçe sürüm İngilizcenin gerisinde kalabilir.*

Motorun ürettiği transfer veritabanını ve iniş analizini gösteren web uygulaması. `public/data/` altındaki JSON dosyalarını okur; motor sunucusu açıksa canlı tasarım ve eksik yörüngeler için onu kullanır.

## Çalıştırma

**Sadece kullanmak için** Node.js gerekmez. Proje ana klasöründe:

```
python -m api.server
```

`http://localhost:8000` hem arayüzü (`web/dist`; bir kez `npm run build` ile derleyin) hem veritabanını hem API'yi sunar.

**Arayüz üzerinde çalışmak için** (Node.js 20+):

```
python -m api.server          (birinci pencere, proje ana klasöründe)
cd web
npm install
npm run dev                   (ikinci pencere; http://localhost:5173, /api isteklerini 8000'e yönlendirir)
npm run build                 (web/dist'i yeniden üretir)
npm run typecheck
npm test                      (tarayıcıdaki hesapların kontrolü: güç bütçesi, Ay'ın gökyüzü motora ve NASA tutulma kataloğuna karşı, nokta analizi)
```

## Veriyi güncelleme

Paketle gelen `public/data/` analitik efemerisle üretilmiş **demo verisidir**; arayüz üst köşede bunu belirtir. Gerçek DE440 verisi için proje ana klasöründe:

```
python scripts/build_database.py --preset year2026 --spice
```

Bu komut tarar, iniş analizini yapar ve `public/data/`'yı yazar: `transfers.json`, `landings.json` ve `trajectories/`. Sunucu her açılışta güncel dosyaları okur.

Doğrulama sayfasının verisi (`validation.json`) ayrı bir komutla üretilir:

```
python scripts/sweep_transfers.py --start 2025-12-07 --end 2026-03-31 --step 3 --tofs 4 6 8 10 12 --families 1 --spice --out data/cache/genova.csv
python scripts/build_validation.py --spice --tests
python scripts/diviner_polar_check.py --spice
python scripts/diviner_polar_diagnose.py --spice
```

Son iki komut Diviner'ın kutup verisiyle karşılaştırmayı (`diviner_polar.json`, ağ gerekir, ~5-10 dk) ve kontrolden sonra yapılan teşhisi (`diviner_polar_diagnostics.json`, isteğe bağlı) üretir.

3D görünümün (`scene3d.json`, `scene3d.bin`, `journeys.json`) ve sıcaklık / güç hesaplayıcısının (`thermal.json`) verisi tahminden sonra:

```
python scripts/build_scene3d.py --spice
python scripts/build_journeys.py --spice
python scripts/build_thermal.py --spice
python scripts/build_ephemeris_table.py --spice
python scripts/check_polar_orientation.py --pole south
python scripts/build_horizon_grid.py --spice
```

## Ekranlar

Üstteki sekmeler: **Browse and plan** (aşağıdakiler), **Anywhere** (`#anywhere`: Ay'ın herhangi bir noktası için gün ışığı, iniş pencereleri, Dünya ve DSN, tutulmalar; tarayıcıda hesaplanır), **Forecast** (`#forecast`: Griffin-1 için kayıtlı zaman ve yer tahmini, bölge uygunluk haritası), **3D view** (`#3d`: iki sahne. Journey: IM-1, IM-2 ve Griffin-1'in fırlatmadan yere temasa yolculuğu, DSN bağlantıları. Landing region: bölgenin LOLA arazisi, GPU'da hesaplanan gölgeler, zaman kaydırıcısı, astronot kamerası, motora karşı gölge kontrolü. WebGL2 gerekir) ve **Validation** (`#validation`).

- **Where do you want to land?** Ay haritası ve bölge karşılaştırma tablosu: iniş penceresi sayısı, en iyi yüzeye Δv, tipik bekleme ve gün ışığı. Bir bölge seçmek tüm görünümleri o bölgeye göre yeniden hesaplar.
- Kutup bölgesi seçilince **ufuk panoraması**: LOLA arazisinin 360° silueti ve Güneş'in o enlemde çıkabileceği en yüksek açı. İniş bloğundaki Güneş grafiği de Güneş yönündeki araziyi gösterir; iniş penceresi arazi ufkunun 0.5° üstünden başlar.
- **Plan a mission to …** (bölge seçilince): tersine sorgu. TLI tarih aralığı, inişten sonra en az gün ışığı, yörüngede en fazla bekleme ve isteğe bağlı yüzeye Δv sınırı verilir; araç bu şartları sağlayan tüm fırlatma pencerelerini (ardışık uygun TLI tarihleri), her pencerenin kaç gün açık kaldığını, en iyi fırlatma tarihlerini sıralı listeler ve seçili transfer için **kayma toleransını** söyler: "fırlatma 4 gün kayabilir, 22 Şubat'a kadar şartlar sağlanır".
- Planlayıcıda ek şartlar: ilk günlerde en az %X güneş enerjisi, inişte DSN istasyonu görünürlüğü; "Copy link to this plan" ile aynı görünümün linki. İniş bloğunda enerji, en uzun gölge ve inişi gören DSN istasyonları.
- **Design a transfer:** motor açıkken herhangi bir tarih, transit süresi, yaklaşma ailesi ve yakalama yörüngesi için transfer tasarlar (~5 sn), tüm bölgeler için iniş analiziyle.
- **Launch window map:** TLI tarihi × transit süresi ısı haritası. Metrikler: LOI, toplam, TLI Δv, C3, v∞; bölge seçiliyken yüzeye Δv, bekleme süresi, inişten sonraki gün ışığı. Taralı hücre: o transferle 30 gün içinde iniş penceresi yok. Ok tuşlarıyla gezilir.
- **… by launch date:** NASA Lunar Browser'ın kendi görünümü; metrik × tarih, renk = transit süresi.
- **Transfer detayı:** yanmalar, zaman çizelgesi (TLI → SOI → LOI → iniş), seçili bölge için iniş bloğu ve Güneş yükselimi grafiği, döndürülebilir 3B yörünge (Dünya ve Ay görünümü).
- **Tablo:** en iyi on transfer veya tümü; grafiklerin erişilebilir tablo karşılığı.
- Filtreler: yaklaşma ailesi, TLI ayı; açık / koyu tema.
- **Validation:** NASA Ames Lunar Browser grafiğiyle karşılaştırma (LOI bandı, aylık minimumlar), uçmuş iki CLPS görevinin geriye dönük testi (IM-1 Odysseus, IM-2 Athena: gerçek iniş anında aydınlatma, yeniden kurulan varış, tahmin edilen fırlatma pencereleri ve gerçek pencereler) regolit sıcaklık modelinin Diviner'a karşı kontrolleri (ekvator ve güney kutbu) ve test paketinin özeti.
- **Forecast'te güç bütçesi:** panel, batarya ve yük girilir; motor noktadaki güneş ışığını en iyi iniş anından itibaren 2 saatlik adımlarla verir; batarya doluluğu, gölgede tükenip tükenmediği, gerekli en küçük batarya ve panel (ikiye bölme ile).

## Yapı

```
src/
├── App.tsx                  düzen, filtreler, seçim, canlı sonuçlar
├── types.ts                 transfers.json, landings.json, yörünge ve API şemaları
├── lib/
│   ├── metrics.ts           karşılaştırılabilir metrikler (birim, iyi yön, bölge gerekir mi)
│   ├── landing.ts           sıkıştırılmış iniş sonuçlarını çözme, sebep metinleri
│   ├── api.ts               motor sunucusu: sağlık, tasarım işi, yörünge
│   ├── color.ts             tek tonlu sıralı renk skalası (açık / koyu)
│   ├── format.ts            tarih ve sayı biçimleri
│   ├── planner.ts           tersine sorgu, fırlatma pencereleri, kayma toleransı
│   ├── urlstate.ts          paylaşılabilir link: durum adres çubuğunda
│   ├── power.ts             güç bütçesi: batarya simülasyonu, en küçük batarya / panel (tests/power.check.mjs)
│   ├── sky.ts               Ay'ın gökyüzü: efemeris tablosu, Güneş / Dünya yönü, DSN, tutulmalar (tests/sky.check.mjs)
│   ├── siteAnalysis.ts      herhangi bir nokta: gün ışığı, iniş pencereleri, iletişim, tutulmalar (tests/site.check.mjs)
│   ├── horizonGrid.ts       kutup (güney / kuzey) LOLA ufuk ızgarası: parça seçimi, dört noktadan karıştırma (tests/horizon.check.mjs)
│   ├── scene3d/             3D görünüm (bağımlılıksız WebGL2)
│   │   ├── data.ts          scene3d dosyası, harita düzlemi ↔ Ay-sabit ↔ sahne dönüşümleri, Güneş / Dünya
│   │   ├── shaders.ts       GLSL; MARCH_GLSL motorun march_sun_clear() fonksiyonunun GPU ikizi
│   │   ├── renderer.ts      ışık geçişi, arazi halkaları, gökyüzü, çizgiler, kontrol ve nokta sorgusu
│   │   ├── journey.ts       yolculuk dosyası, zaman içinde enterpolasyon (konum, yönelim kuaternionları)
│   │   ├── journeyRenderer.ts  Dünya, Ay (LOLA kutup arazisi), yol, uzay aracı, DSN bağlantıları
│   │   └── math.ts          4x4 matrisler
│   └── hooks.ts             veri yükleme, sunucu durumu, yörünge, genişlik, tema, sayfa (#hash)
└── components/
    ├── SitePanel.tsx, SiteMap.tsx      bölge seçimi ve karşılaştırma
    ├── DesignPanel.tsx                 canlı tasarım formu
    ├── Porkchop.tsx, SolutionSpace.tsx grafikler
    ├── TransferDetail.tsx, LandingBlock.tsx, SunChart.tsx
    ├── TrajectoryView.tsx              bağımlılıksız 3B kanvas projeksiyonu
    ├── TransferTable.tsx, Legend.tsx
    ├── PlannerPanel.tsx                görev planlayıcı (pencere şeridi, tablolar)
    ├── HorizonChart.tsx                LOLA ufuk panoraması
    ├── ForecastPage.tsx                yaklaşan görev tahmini, bölge haritası
    ├── ScenePage.tsx                   3D görünüm: sahne seçimi; bölge sahnesi (kameralar, zaman, katmanlar, gölge kontrolü)
    ├── JourneyView.tsx                 3D yolculuk: görev, kamera, zaman çizelgesi, gerçekle karşılaştırma
    ├── ThermalSection.tsx              regolit sıcaklıkları: Diviner kontrolü (Validation), adaylar (Forecast)
    ├── PowerBudget.tsx                 güç bütçesi hesaplayıcısı (Forecast)
    ├── AnywherePage.tsx                Ay'ın her yeri: harita, nokta analizi, tablolar
    ├── DivinerPolarSection.tsx         güney kutbunda model ve Diviner ölçümleri (Validation)
    └── ValidationPage.tsx              doğrulama sayfası
```

## Tasarım notları

- Görsel dil NASA teknik raporlarındaki yörünge çizelgelerinden: soğuk tonlu milimetrik zemin, lacivert mürekkep, veri tek tonlu mavi skala ("koyu = kötü" her metrikte), **macenta yalnızca seçili transfer için**.
- Yazı tipi TeX Gyre Heros (Helvetica'nın serbest ikizi), `public/fonts/` içinde, GUST Font License.
- Açık ve koyu tema; koyu temada renk skalası koyu zemine göre ayrıca seçili.
