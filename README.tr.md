# CLPS Lunar Mission Browser

*English: [README.md](README.md). Bu Türkçe sürüm İngilizcenin gerisinde kalabilir.*

NASA Space Apps Challenge 2026, *CLPS Lunar Mission Browser* görevi: olası iniş bölgelerini ve zaman pencerelerini karşılaştıran bir araç. Modüler bir Dünya-Ay uçuş dinamiği motoru, ondan üretilen bir transfer veritabanı, canlı tasarım için bir API ve bunları birleştiren bir web arayüzü.

Ana soru: **"Şu bölgeye inmek istiyorum; hangi gün fırlatırsam en az Δv ile, ne kadar bekleyerek ve ne kadar gün ışığıyla inerim?"**

## Hızlı başlangıç (Windows komut satırı)

Proje ana klasöründe (`pyproject.toml` olan yer):

```
python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev,spice]"
python scripts/download_kernels.py
pytest
```

macOS / Linux'ta `activate` satırı: `source .venv/bin/activate`.

**Veritabanını üret** (tarama → iniş analizi → web verisi, tek komut):

```
python scripts/build_database.py --preset quick --spice
```

| Ön ayar | Kapsam | Transfer | Süre (8 çekirdek) |
|---|---|---|---|
| `quick` | Ocak 2026, 3 günde bir, 4/5/6/8 gün, iki aile | ~88 | birkaç dk |
| `genova` | Ara 2025 - Mar 2026, 4-12 gün, güney ailesi (NASA karşılaştırması) | 195 | ~5 dk |
| `year2026` | 2026'nın tamamı, 2 günde bir, 4/5/6/8/10 gün, iki aile | 1.830 | ~30 dk |

Tarama kaldığı yerden devam eder: yarıda kesilirse aynı komutu tekrar çalıştırın.

**Arayüzü aç:**

```
python -m api.server
```

**Kutup bölgeleri için LOLA arazisi** (Malapert A, Mons Mouton; bir kez):

```
python scripts/download_terrain.py
python scripts/build_horizons.py --spice
python scripts/build_database.py --preset year2026 --spice --skip-sweep
```

İlk komut LOLA yükseklik haritasını (`LDEM_75S_120M`) ve NASA'nın aydınlatma haritasını (`AVGVISIB_75S_120M`) indirir, ~233 MB. İkincisi her kutup bölgesinin ufkunu hesaplar, `engine/surface/horizons/` altına küçük JSON dosyaları olarak kaydeder ve NASA haritasıyla karşılaştırır (birkaç dakika). Üçüncüsü iniş analizini arazili ufukla yeniden yapar; tarama tekrarlanmaz.

**Yaklaşan görev tahmini (Griffin-1)**, arazi hazırlandıktan sonra:

```
python scripts/build_forecast.py --spice
python scripts/verify_forecast.py
python scripts/build_scene3d.py --spice
python scripts/build_journeys.py --spice
python scripts/build_thermal.py --spice
python scripts/build_ephemeris_table.py --spice
python scripts/check_polar_orientation.py --pole south
python scripts/build_horizon_grid.py --spice
python scripts/build_slope_map.py
```

Kuzey kutbu için (isteğe bağlı, +116 MB indirme):

```
python scripts/download_terrain.py --north
python scripts/check_polar_orientation.py --pole north
python scripts/build_horizon_grid.py --spice --pole north
python scripts/build_slope_map.py --pole north
```

`build_scene3d` **3D görünümün** verisini üretir (`web/public/data/scene3d.json` + `scene3d.bin`, ~2 MB, 1-2 dakika): bölgenin arazisi, saatlik Güneş ve Dünya yönleri ve gölge kontrolü için motorun referans değerleri. Tahminden sonra çalıştırılmalı, çünkü kontrol noktaları olarak tahminin ilk 10 adayını kullanır. `build_journeys` **3D yolculuğun** verisini üretir (`journeys.json` + `moon_cap.bin`, ~1 dakika); yeni transfer tasarlamaz, doğrulama ve tahmin adımlarının `data/cache` altındaki sonuçlarını kullanır. `build_thermal` adaylarda yüzey sıcaklığını ve güç hesaplayıcısının kullandığı güneş ışığını üretir (`thermal.json`). `build_ephemeris_table` **Anywhere** sayfasının tablosunu üretir (`ephem_moon.bin`, ~2 MB, 2024-2028 saatlik; tahminden bağımsız, ~1 dk). `check_polar_orientation` haritanın hangi yönde okunacağını adlı kraterlerle doğrular (aşağıda); `build_horizon_grid` bu doğrulama geçmeden çalışmaz. `build_horizon_grid` kutup başlığının LOLA ufuk ızgarasını ve gölgeli kabartma haritasını üretir (~10 dk, ~24 MB parça dosyalar).

GitHub'a koyma, sitenin yayınlanması ve tahminin kayda geçirilmesi adım adım: [`docs/KAYIT.md`](docs/KAYIT.md).

İlk komut ~2.400 transfer tasarlar ve Mons Mouton-Nobile bölgesinde 1.681 noktayı tarar (8 çekirdekte ~25 dk, kaldığı yerden devam eder). Sonucu `web/public/data/forecast.json` dosyasına zaman damgası ve SHA-256 özetiyle yazar. Bu dosya **fırlatmadan önce** yayınlanmalı. Bir commit'in tarihi commit'i yapanın kendi bilgisayarından gelir ve tek başına hiçbir şey kanıtlamaz; kayıt, bir GitHub Release'i ve archive.org kopyasıdır (aşağıda [Kayıt](#kayıt)). İkinci komut dosyanın kayıttan sonra değişmediğini kontrol eder.

**Doğrulama sayfasını üret** (NASA karşılaştırması + uçmuş görevlerin geriye dönük testi + test paketi):

```
python scripts/sweep_transfers.py --start 2025-12-07 --end 2026-03-31 --step 3 --tofs 4 6 8 10 12 --families 1 --spice --out data/cache/genova.csv
python scripts/sweep_transfers.py --start 2026-01-05 --end 2026-01-13 --step 1 --tofs 4 4.5 5 5.5 6 6.5 7 --families 1 --spice --out data/cache/jan_minimum.csv
python scripts/build_validation.py --spice --tests
python scripts/diviner_polar_check.py --spice
python scripts/diviner_polar_diagnose.py --spice
```

İlk iki komut NASA grafiğinin penceresini (195 transfer, ~5 dk) ve Ocak minimumu çevresini (63 transfer, ~2 dk) tarar; arayüz verisine dokunmaz. İkincisi IM-1 ve IM-2 için ~2.000 transfer tasarlar (8 çekirdekte ~20 dk, kaldığı yerden devam eder) ve `web/public/data/validation.json`'u yazar.

Tarayıcıda `http://localhost:8000`. Sunucu hem arayüzü (`web/dist`) hem veritabanını hem de canlı tasarım API'sini sunar; Node.js gerekmez. Arayüz geliştirmek için ikinci pencerede `cd web`, `npm install`, `npm run dev` (adres `http://localhost:5173`, API isteklerini 8000'e yönlendirir).

## Mimari

```
engine/
├── core/          zaman, sabitler, State, çerçeveler (Ay-Güneş çerçevesi dahil)
├── ephemeris/     EphemerisProvider: Analytic (IAU Ay yönelimi dahil) | Spice (DE440, MOON_PA) | Cached (tablo)
├── dynamics/      ForceModel arayüzü + modeller + DynamicsModel (birleştirici)
├── propagators/   propagate(), Trajectory, event'ler (periapsis, çarpma, gölge, SOI, en yakın geçiş)
├── orbits/        Kepler elemanları, B-plane geometrisi
├── targeting/     Residual arayüzü, Control'ler, TargetingProblem, Newton (active-set) / LM
├── mission/       TLI -> LOI transfer tasarımcısı, patched-conic ilk tahmin
├── surface/       iniş bölgeleri, Güneş/Dünya azimut ve yükselimi, LOLA arazi ufku, iniş fırsatı analizi
├── database/      web dışa aktarımı (transferler, inişler, yörüngeler)
├── validation/    korunum residual'ları, ileri-geri hata, kuvvet bütçesi,
│                  uçmuş görevler (IM-1, IM-2), geriye dönük test, NASA referansı
└── forecast/      yaklaşan görevler (Griffin-1): zaman tahmini, bölge uygunluk taraması
api/               bağımlılıksız HTTP sunucu: canlı tasarım + arayüz
web/               React + Vite arayüzü (bkz. web/README.md)
scripts/           build_database, build_validation, build_horizons, build_forecast, sweep_transfers, export_web_data, download_kernels, ...
data/              SPICE çekirdekleri, tarama CSV'leri, efemeris tabloları (git'e girmez)
```

Birimler her yerde: km, s, km/s, km³/s². Epoch = J2000'den itibaren TDB saniyesi. State = `[x, y, z, vx, vy, vz]`, J2000 eylemsiz çerçeve.

### İki temel sözleşme

**`ForceModel`**: her fiziksel etki bağımsız bir modül.

```python
class MyForce(ForceModel):
    name = "my_force"
    def acceleration(self, t, r, v, ctx): ...   # km/s²
    def potential(self, t, r, ctx): ...         # opsiyonel; korunumlu ise enerji testi açılır

dyn.add(MyForce()); dyn.set_enabled("sun_third_body", False); dyn.breakdown(t, y)
```

Mevcut modeller: `PointMassGravity`, `ZonalHarmonics` (Ay için J2-J7), `ThirdBodyGravity`, `SolarRadiationPressure`.

**`Residual`**: hedeflenen her büyüklük bağımsız bir modül. `normalized = (ölçülen - hedef) / tolerans`, |değer| ≤ 1 sağlandı demektir. `TargetingProblem(kontroller, residual'lar, simülatör)` + `solve()`.

## TLI → LOI transfer tasarımcısı

`design_transfer(eph, TransferSpec(tli_epoch, tof_days, lunar_inc_deg=90, family=+1))`

- Park yörüngesi + TLI → Ay'ın etki küresi → periselene; iki aşamalı hedefleme (B-plane, sonra gerçek periselene).
- Kontroller: park yörüngesi RAAN'ı ve eğimi (fırlatma azimutu), TLI noktası, TLI Δv.
- Aileler: `+1` Ay'ın güneyinden geçer (South pass), `-1` kuzeyinden (North pass). Aynı yörünge düzlemini ters yönde dolaşırlar.
- Çıktılar: TLI/LOI/toplam Δv, C3, v∞, RAAN(Ay-Güneş), periselene enlem/boylamı, yakalama yörüngesinin düzlemi.

**Büyük Ay durağanlığı:** 2024-2026'da Ay'ın deklinasyonu ±28.5°'ye ulaşıyor; tasarımcı park eğimini gerektiğinde ~30°'ye çıkararak, Δv cezası olmadan, iki aileyi de çözüyor.

## İniş analizi

LOI'den sonra yörünge düzlemi uzayda neredeyse sabit, Ay altında 27.3 günde bir döner. Bir bölge ayda iki kez yörünge düzleminden geçer; arada ulaşmak için düzlem değişikliği gerekir. Her (transfer, bölge) çifti için 10 dakikalık adımlarla 30 günlük bekleme taranır:

- Güneş bölgenin penceresinde ve yükseliyor mu (sabah inişi gün ışığını en uzun tutar)? Ekvator ve orta enlemlerde 3°-20°, kutup bölgelerinde > 0.5°.
- Dünya ufkun üstünde mi (iniş sırasında doğrudan iletişim)? Uzak taraf bölgelerinde röle varsayılır.
- Düzlem değişikliği bütçe içinde mi (varsayılan 150 m/s)?

En ucuz seçeneğe 10 m/s yakın olan en erken an seçilir. Sonuç: iniş zamanı, bekleme süresi, düzlem değişikliği Δv'si, iniş Δv'si (tahmin), toplam yüzeye Δv, inişteki Güneş ve Dünya yükselimi, inişten sonraki gün ışığı süresi.

**Bulgu:** Ekvator bölgeleri için gereken düzlem değişikliği TLI tarihi iki gün kaydıkça 1.500 → 800 → 85 m/s'ye iniyor. Yani doğru fırlatma tarihi düzlem değişikliğini neredeyse bedava yapıyor; NASA aracındaki RAAN(Ay-Güneş) filtresi tam olarak bunu yakalıyor.

**Bölgeler** (`engine/surface/sites.py`, kaynaklar dosyada): Tranquility Base, Mare Crisium (Blue Ghost 1), Reiner Gamma (IM-3), Mons Gruithuisen Gamma (Lunar-VISE), Malapert A (IM-1), Mons Mouton (IM-2), Schrödinger havzası (APEX 1.0).

**Arazi (LOLA):** kutup bölgelerinde Güneş ufkun birkaç derece üstünde ve altında dolaşır; bölgenin ne zaman aydınlandığına çevredeki dağlar karar verir. `engine/surface/terrain.py` LOLA `LDEM_75S_120M` haritasından her bölge için her 0.5° azimutta ufuk yüksekliğini hesaplar: 250 km'ye kadar arazi, Ay'ın eğriliği dahil, gözlemci yerden 2 m yüksekte. İniş kuralı değişmedi: Güneş 0.5° yukarıda ve yükseliyor olmalı. Değişen tek şey, bunun düz ufka göre değil gerçek arazi ufkuna göre ölçülmesi. Dünya görünürlüğü ve inişten sonraki gün ışığı da araziye göre hesaplanır. Ufuk dosyası olmayan bölgeler düz ufukla devam eder.

**Arazinin bağımsız kontrolü:** NASA Goddard'ın kutup aydınlatma haritası (Mazarico vd. 2011) aynı ızgarada, aynı LOLA haritasından, 18.6 yıl boyunca bir pikselin aydınlık kaldığı zaman oranını verir. `build_horizons.py` aynı oranı kendi ufkumuz ve efemerisimizle her bölgenin çevresindeki 25 pikselde hesaplar ve karşılaştırır. Geçme eşiği gerçek veriyle ilk çalıştırmadan önce koda yazıldı (`engine/validation/illumination.py`): her bölgede medyan fark ≤ 3, en büyük fark ≤ 8 yüzde puanı. Bu kontrol IM-1/IM-2 testinden tamamen bağımsız; ufuk hesabını, yükseklikleri, kutba uzaklığı, Güneş azimutunu ve Ay yönelimini birlikte sınar. **Sonuç (DE440, 2005-2023): iki bölgede de geçti:** Malapert A medyan 0.2, en büyük 3.6 puan, korelasyon 0.983; Mons Mouton medyan 0.2, en büyük 3.0 puan, korelasyon 0.998. **Düzeltme (v0.15):** daha önce burada bu kontrolün harita yönünü de sınadığı yazıyordu; bu yanlıştı. 18.6 yıl boyunca Güneş gökyüzünde eşit dolaştığı için aynalanmış ya da döndürülmüş bir harita aynı ortalamaları verir; sentetik bir testte dört okumanın dördü de geçti. Harita yönü artık adlı kraterlerle sınanıyor: `python scripts/check_polar_orientation.py --pole south` (ve `--pole north`). Her kutupta, kutbun çevresine yayılmış altı büyük kraterin (IAU koordinatları) haritanın dört olası okunuşunda derinliği ölçülür; doğru okunuşta hepsi derin bir çanak, yanlışta "taban" başka yere düşer. Ölçüt gerçek veriden önce yazıldı: her krater en az 500 m derin olmalı ve tek bir okunuş geçmeli. Sentetik haritalarda (iki kutup, dört doğru okunuş) her seferinde tam doğru okunuşu buluyor (`tests/test_orientation.py`).

**Model sınırları:** arazi sadece kutup bölgelerinde (75°S-90°S haritası); ekvator bölgeleri düz ufukla. Yörünge düzlemi kayması sadece Ay J2'sinden, iniş Δv'si basit bir model (15 km periselene, %6 kayıp, 60 m/s marj), yörünge içi faz (< 2 saat) ihmal.

## Görev planlayıcı (arayüzde)

Bölge seçilince açılan **Plan a mission** paneli tersine sorgu yapar: "X bölgesine A-B tarihleri arasında, en az N gün gün ışığıyla, yörüngede en fazla W gün bekleyerek in." Sonuç:

- **Fırlatma pencereleri:** şartları sağlayan ardışık TLI tarihleri ve her pencerenin kaç gün açık kaldığı (veritabanının tarih aralığı kadar hassas, `year2026` için ±2 gün).
- **Kayma toleransı:** seçili transferin fırlatması kaç gün kayabilir ve hâlâ şartlar sağlanır.
- **En iyi fırlatma tarihleri**, yüzeye Δv'ye göre sıralı; tıklayınca transfer açılır.

Örnek (analitik demo verisi, Malapert A, ≥ 7 gün ışık, ≤ 5 gün bekleme): 2026'da 12 pencere, çoğu 12-14 gün açık; Nisan-Haziran pencereleri 8 güne düşüyor.

## Yaklaşan görev tahmini: Griffin-1

Astrobotic'in Griffin-1 görevi (CLPS, 2026'nın son çeyreği, Falcon Heavy) Nobile krateri ve Mons Mouton bölgesine, IM-2'nin indiği alana gidiyor; hedef yüzeyde en az 5 gün çalışmak. Kesin iniş noktası ve tarihi yayımlanmadı. Arayüzdeki **Forecast** sekmesi iki soruyu cevaplar:

- **Ne zaman:** 1 Kasım 2026 - 28 Şubat 2027 arasındaki her TLI günü için, IM-1/IM-2'de test edilen kurallarla (4-7 günlük transit, 80-100° yörünge, 4 gün içinde iniş, Güneş arazi ufkunun 0.5° üstünde ve yükseliyor, Dünya görünür) ve duyurulan 5 günlük güneş şartıyla, inilebilecek günler ve fırlatma pencereleri. Referans nokta Athena'nın iniş noktası, çünkü Griffin'inki yayımlanmadı.
- **Nerede:** 80 × 80 km'lik bölgede 2 km aralıklı 1.681 noktanın her biri için kendi arazi ufku, iniş anları, inişten sonraki güneş, Dünya görünürlüğü ve eğim. Ölçütler NASA'nın VIPER alanını seçerken kullandıklarıyla aynı: aydınlanma, Dünya görünürlüğü, eğim. Sonuç, bu ölçütlere göre en uygun yerlerin sıralı listesi ve haritası.

**Dürüstlük kuralları:** Duyurulan bilgiler kaynaklarıyla, bizim varsayımlarımız ayrı listelenir. Harita "Astrobotic şuraya inecek" demez; metre ölçeğindeki kayalar, yükün hedefleri ve şirketin kuralları 120 m'lik haritada görünmez. Geçmiş görevlerden gelen kalibrasyon da yazılır: arazili kurallar IM-1'de gerçek inişi 36 dakika farkla buldu, IM-2'de (aynı nokta) 1 gün geç kaldı. Bu yüzden tahmin edilen iniş tarihleri ±2 güne kadar belirsizlikle okunmalı (sayfa bunu kalibrasyon verisinden yukarı yuvarlayarak hesaplar).

### Kayıt

Griffin-1 tahmini fırlatmadan önce yapıldı ve yayınlandı. Commit tarihi commit'i yapanın kendi saatinden gelir ve hiçbir şey kanıtlamaz; bu yüzden kayıt, saatini başkalarının tuttuğu zaman damgalarına dayanır:

| Kayıt | Saati tutan | Zaman (UTC) |
|---|---|---|
| [GitHub Release `griffin-1-forecast`](https://github.com/dundaryusuf566-maker/clps-lunar-browser/releases/tag/griffin-1-forecast), `forecast.json` ekli | GitHub sunucusu | 2026-10-27 18:06 |
| [Dosyanın `fbc2b6b` commit'indeki halinin archive.org kopyası](https://web.archive.org/web/20261027192746/https://raw.githubusercontent.com/dundaryusuf566-maker/clps-lunar-browser/fbc2b6bb7f96caa293df7178dfa92ac63d37d0f2/web/public/data/forecast.json) | Internet Archive | 2026-10-27 19:27:46 |
| [Release sayfasının archive.org kopyası](https://web.archive.org/web/20261027192833/https://github.com/dundaryusuf566-maker/clps-lunar-browser/releases/tag/griffin-1-forecast) | Internet Archive | 2026-10-27 19:28:33 |
| `web/public/data/forecast.json.ots`: dosyanın SHA-256'sının OpenTimestamps kanıtı | Bitcoin zinciri | 2026-10-27'de damgalandı; `ots upgrade` / `ots verify` tamamlar ve doğrular |

- Tahmin içeriğinin `{mission, time, region}` SHA-256'sı: `c87ac8d7a9756a70ed4d80d5f58c8c3ae8b0d3a68bbf4b067e9f7215b712265a` (`python scripts/verify_forecast.py`)
- Dosyanın tamamının SHA-256'sı (OpenTimestamps kanıtının kapsadığı): `e813009f9b6685d3bf1982fa840121124542ad64c900f8152790fd178d074c3d` (Windows'ta `certutil -hashfile forecast.json SHA256`, diğerlerinde `sha256sum`)
- Commit edilmemiş değişiklik olmadan `889f6a1` kodundan üretildi (`meta.git_commit`, `meta.git_code_dirty`); motor 0.19.1, JPL DE440, LOLA LDEM_75S_120M.
- **Önceki sürüm, açıkça:** `2544b05` commit'i (26 Ekim 2026'da gönderildi) 18 Ekim'de commit edilmemiş kodla üretilmiş bir tahmin içeriyordu (SHA-256 `3376f805…7726`). Tahmini commit edilmiş kodla yeniden ürettik. İçerikteki tek fark `time.calibration`: 18 Ekim'den sonra doğrulamaya eklenen Blue Ghost Mission 1'in geriye dönük sapmasını (1.41 gün) da listeliyor; bilgi amaçlı, tahminde kullanılmıyor. Fırlatma pencereleri, iniş zamanları, bölge adayları ve sıralama birebir aynı.

Bundan sonra `forecast.json` değiştirilmez; her push'ta CI SHA-256'yı yeniden kontrol eder. Yeni bir tahmin (ör. IM-3) ayrı bir dosya ve ayrı bir Release olur.

## Yer istasyonları, enerji ve paylaşılabilir link

- **DSN görünürlüğü** (`engine/surface/ground.py`): her iniş anı için NASA'nın üç DSN kompleksinden (Goldstone, Madrid, Canberra) hangilerinin iniş noktasını 10°'nin üstünde gördüğü. Dünya yönelimi IAU 1976 presesyonu ve ortalama yıldız zamanıyla hesaplanır (nutasyon ve kutup kayması ihmal, hata ~0.01°). İstasyon koordinatları Wikipedia'dan; 10° maske bizim varsayımımız. Planlayıcıda "iniş bir DSN istasyonunun görüş alanında olsun" şartı var. Not: ticari görevler DSN dışında kendi yer istasyonlarını da kullanabilir (Intuitive Machines'in kendi ağı var), bu yüzden geçmiş görevler için bu bilgi kontrol değil, sadece bilgi olarak gösterilir.
- **Enerji bütçesi:** inişten sonra güneş diskinin arazi ufkunun üstünde kalan payı (%100 = tam Güneş sürekli) ve en uzun gölge süresi. Planlayıcıda varsayılan pencere 5 gün; Griffin-1 tahmininde bir Ay günü (14 gün). Tahminde 5 gün kullanmak anlamsızdı: iniş kuralı zaten 5 gün kesintisiz güneş istediği için her nokta ~%100 ve 0 saat gölge çıkıyordu. 14 günlük pencere, ilk Ay gecesine ne kadar erken girildiğini ve arazi gölgelerini noktalar arasında ayırt eder; 14 gün bizim seçimimiz (bir varsayım), duyurulmuş bir görev süresi değil. Kutup bölgelerinde arazi Güneş'i gün içinde saatlerce kapatabilir; bu, pil kapasitesini belirleyen sayıdır. Panel yönelimi bilinmediği için diskin görünen payı kullanılır, panel verimi değil.
- **Paylaşılabilir link:** seçilen bölge, metrik, filtreler, planlayıcı şartları ve seçili transfer adres çubuğunda (`#browse?site=...&minsun=...`) saklanır. "Copy link to this plan" düğmesi aynı görünümü açan linki kopyalar.

## Ay'ın her yeri (Anywhere sayfası)

Haritada herhangi bir noktaya tıklanır (ya da enlem / boylam girilir, bilinen bir bölge seçilir); seçilen dönem (30-365 gün) için tarayıcı saat saat şunları hesaplar: Güneş ve Dünya'nın o noktanın gökyüzündeki yükselimi ve azimutu, gün doğumu / batımı ve gece uzunlukları, iniş pencereleri (motorun her bölge için kullandığı ışık ve iletişim kuralı: Güneş ufkun 3-20° üstünde ve yükseliyor, kutupta 0.5-90°; Dünya en az 2°), DSN istasyonlarının (Goldstone, Madrid, Canberra, 10° maske) noktayı görmesi, uzak yüzde "Dünya hiç doğmuyor, röle gerekli" uyarısı ve Ay tutulmaları (Dünya'nın Güneş'in önünden geçmesi; güneş enerjisiyle çalışan bir iniş aracı için ani güç kaybı). Link paylaşılabilir (`#anywhere?lat=..&lon=..&from=..&days=..`).

Sitenin arkasında Python yok: `scripts/build_ephemeris_table.py` DE440'tan Güneş ve Dünya'nın Ay'a göre yönlerini ve Ay'ın yönelimini saatlik bir tabloya yazar (`web/public/data/ephem_moon.bin`), gerisini tarayıcı yapar (`web/src/lib/sky.ts`, `siteAnalysis.ts`). Aynı tablo üretilirken motorun kendi cevapları da 9 noktada (kutuplar, CLPS bölgeleri, uzak yüz, kenar) 60 rastgele anda yazılır (`web/tests/ephem_reference.json`); `web/tests/sky.check.mjs` tarayıcının sonuçlarını bunlarla karşılaştırır: Güneş ve Dünya yönü 0.01° içinde (geliştirme ortamında en kötü fark 0.00008°), DSN maskeleri birebir. Tutulmalar NASA'nın kataloğuna karşı sınanır: 2024-2028 arasındaki 12 Ay tutulmasının hepsi bulunmalı, en derin anı NASA'nınkinden 15 dakikadan az sapmalı, umbral büyüklüğü 0.5'ten büyük olanlarda Ay'ın merkezinden Güneş tamamen kapanmalı (bu kontrol DE440 tablosu gerektirir; analitik Ay birkaç derece kayık). `web/tests/site.check.mjs` kodumuzdan bağımsız gerçeklere karşı sınar: ekvatorda Güneş yılın ~%50'si yukarıda, Ay günü ~14.77 gün, gün doğumları sinodik ay aralığında (29.27-29.83 gün), Dünya'ya bakan noktada Dünya hep yukarıda, uzak yüzde hiç, kenarda arada bir; her iniş penceresi kurala uyuyor.

**Kutupta gerçek arazi: ufuk ızgarası** (`engine/surface/horizon_grid.py`, `scripts/build_horizon_grid.py`). Her iki kutupta, kutuptan 75°'ye kadar, kutupsal stereografik düzlemde her 5 km'de bir noktanın LOLA ufku (1° azimut, 2 m gözlemci) hesaplanır ve parça dosyalar halinde yazılır; tarayıcı yalnızca tıklanan noktanın çevresindeki parçaları indirir ve dört komşu noktanın ufkunu çift doğrusal (bilinear) olarak karıştırır. Hız için ufuk, 3D görünümün gölgelerinde kullanılan ve orada sınanmış adım planı ve harita seviyeleriyle hesaplanır (noktaya 15 km'ye kadar 120 m harita, 100 km'ye kadar 360 m blok ortalamaları, ötesi 1.2 km); motorun tam `compute_horizon`'una karşı sentetik haritada medyan 0.0000°, p95 0.01°, en kötü 0.07° (`tests/test_horizon_grid.py`) ve nokta başına ~7 kat hızlı. Ara noktalardaki hata ölçülür, varsayılmaz: betik başlıkta 300 rastgele noktada, karıştırılmış ufku noktanın kendi ufkuyla karşılaştırır, hem ufuk derecesi olarak hem de iniş aracı için önemli olan sayı olarak, 2026'da Güneş'in arazinin üstünde kaldığı süre (yılın yüzdesi); aynı sayıyı düz ufuk için de verir. Sonuçlar JSON'a ve sayfaya yazılır. Sentetik haritada: karıştırılmış ufukla medyan 1.6, p90 6.3 yüzde puanı fark; düz ufukla medyan 13.6, p90 34.8. Gerçek LOLA'da (güney, 300 nokta): hızlı ufuk tam hesaptan medyan 0.0°, p99 0.05° farklı; karıştırılmış ufukla Güneş süresi medyan 2.5, p90 11 puan sapıyor, düz ufukla medyan 13.1, p90 36 puan. Yani ızgara düz ufka göre çok daha iyi ama ara noktalarda yakın arazi (krater kenarı / içi) karışıyor; sayfa bu sayıları gösteriyor. **Daha sık ızgara denendi:** 2.5 km aralıkla (105.000 nokta, 85 MB) aynı 300 noktada Güneş süresi hatası medyan 1.5, p90 7.5 puan. Karar ölçütü denemeden önce yazılmıştı: p90 6 puanın altına inerse 2.5 km'ye geçilecekti. İnmedi (7.5), bu yüzden 5 km'de kalındı (4 kat küçük, 4 kat hızlı). `web/tests/horizon.check.mjs` tarayıcının karıştırmasının Python'unkiyle birebir aynı olduğunu (10⁻⁵° içinde) ve kutup haritasındaki tıklamanın projeksiyonu doğru tersine çevirdiğini sınar. Sayfada ufuk panoraması, Güneş yönündeki arazi ve arazi / düz ufuk karşılaştırması için bir anahtar var.

**Haritanın yönü** (`scripts/check_polar_orientation.py`, `tests/test_orientation.py`): bir kutupsal harita dört şekilde okunabilir (x ve y düz ya da aynalı); yanlış okunursa arazi her noktanın çevresinde yanlış yönde durur ve Güneş yanlış saatlerde kaybolur. PDS'nin projeksiyon belgesi tek formül veriyor ama işaretleri bizim güney okumamızla doğrudan örtüşmüyor; bu yüzden yön varsayılmıyor, sınanıyor: her kutupta, kutbun çevresine yayılmış altı büyük kraterin IAU konumunda derinliği dört okunuşta ölçülür (kuzey: Peary, Byrd, Hermite, Rozhdestvenskiy, Plaskett, Hevesy; güney: Amundsen, Cabeus, Shoemaker, Sverdrup, Nobile, Haworth). Ölçüt önceden yazıldı: her krater en az 500 m derin olmalı ve tek bir okunuş geçmeli. Sentetik haritalarda (iki kutup, her olası doğru okunuş) her seferinde tam doğru okunuşu buluyor. Ufuk ızgarası bu kontrol geçmeden üretilmez. **Gerçek veride sonuç:** güney (+1, −1) ve kuzey (+1, +1) okunuşları, dört okunuş içinde tek geçenler; doğru okunuşta kraterler 0.8-3.1 km derin, yanlışlarda en az biri sığ ya da tümsek. Sonuçlar Validation sayfasında. Kuzey ufuk ızgarası (300 nokta): Güneş süresi hatası medyan 3.4, p90 15.0 puan (düz ufuk 12.0 / 38.6); güneyden biraz kötü, yakın arazi kuzeyde daha engebeli.

**Her noktada zemin sıcaklığı ve güç bütçesi** (`web/src/lib/regolith.ts`, `siteThermal.ts`, v0.17). Regolit modeli (aşağıda, Regolit sıcaklıkları) tarayıcıya satır satır taşındı. Seçilen noktanın saatlik güneş ışığı tablodan hesaplanır (Güneş uzaklığı, yükselimi, diskin ufkun üstündeki payı; kutup ızgarasının kapsadığı yerlerde LOLA ufku, başka yerlerde düz ufuk), toprak `build_thermal` ile aynı şekilde ısındırılır (noktanın kendi güneş ışığıyla 365 gün, 6 geçiş, ardından 30 günlük giriş) ve dönem boyunca yüzey sıcaklığı çizilir: en düşük / en yüksek / ortalama ve 150 K altındaki süre. Aynı saatlik güneş ışığı Forecast sayfasındaki güç bütçesi hesaplayıcısına verilir (artık iki sayfada aynı bileşen); başlangıç bir iniş penceresi ya da dönemin başı seçilebilir. Panel varsayılanı enleme göre: kutupta dikey (Güneş alçakta), başka yerlerde yatay, çünkü ekvatorda öğlen Güneş tepedeyken dikey panel neredeyse hiç güç almaz. Yeni seçenek: hep Güneş'e dönük (iki eksenli) panel. Bir yıllık ısınma tarayıcıda ~0.3-0.6 s sürüyor.

Sınama (`web/tests/regolith.check.mjs`, ölçütler kod çalıştırılmadan dosyaya yazıldı): (1) aynı güneş ışığında tarayıcı ve motor aynı sıcaklığı vermeli, 0.05 K içinde. `scripts/build_regolith_reference.py` motoru efemeris ve harita gerektirmeyen üç yapay durumda çalıştırır (ekvator, alçak Güneşli ve ufkun diski kestiği bir kutup noktası, 5 dakikalık adımlarla 5 saatlik bir tutulma) ve sonucu repoya konan `web/tests/regolith_reference.json`'a yazar; fark 10⁻¹³ K. `tests/test_regolith_reference.py` bu dosyanın motorun bugünkü haliyle aynı olduğunu kontrol eder (motor değişirse eski dosya fark edilir). (2) Ekvatorda Diviner'ın öğlen / gece yarısı / şafak öncesi değerleri 5 K içinde (385.2 / 101.8 / 95.6 K). (3) DE440 tablosu ve DE440 ile üretilmiş `thermal.json` varsa, tarayıcının tüm zinciri (tablo, Güneş, ısınma, model) `build_thermal`'ın düz zemin noktasına karşı iniş dönemi boyunca 2 saatte bir: en büyük fark ≤ 1.0 K, ortalama mutlak fark ≤ 0.2 K. **Sonuç (DE440): geçti**, 1717 örnekte en büyük fark 0.05 K, ortalama 0.025 K (61.9-180.5 K, iki tarafta aynı). Geliştirme ortamında analitik tabloyla da 10⁻⁵ K. Ayrıca, sayılmadan raporlanan: adaylarda tarayıcının sonucu (düz zemin, 5 km ızgaradan karıştırılmış ufuk) ile `build_thermal`'ın doğrudan güneşli sonucu (noktanın kendi 0.5°'lik LOLA ufku ve eğimli zemin). Bu karşılaştırma tarayıcının dışarıda bıraktıklarının boyutunu gösteriyor ve **büyük**:

| Nokta | Eğim | Ortalama \|ΔT\| | En düşük: tarayıcı / motor | En yüksek: tarayıcı / motor |
|---|---|---|---|---|
| Mons Mouton (IM-2) | 2.4° | 12.4 K | 60.5 / 64.7 K | 180.4 / 202.1 K |
| Aday 1 | 3.3° | 84.2 K | 29.8 / 65.6 K | 145.1 / 202.4 K |
| Aday 2 | 4.9° | 22.2 K | 54.4 / 52.5 K | 180.5 / 140.2 K |
| Aday 3 | 9.7° | 49.1 K | 51.1 / 68.6 K | 171.2 / 227.1 K |
| Aday 4 | 4.9° | 63.3 K | 35.1 / 62.0 K | 135.9 / 185.4 K |
| Aday 5 | 8.5° | 56.1 K | 49.6 / 69.4 K | 168.6 / 227.7 K |
| Aday 6 | 7.5° | 32.2 K | 61.3 / 71.4 K | 182.5 / 239.5 K |
| Aday 7 | 3.8° | 18.8 K | 59.6 / 57.5 K | 184.1 / 164.0 K |
| Aday 8 | 2.1° | 10.9 K | 58.9 / 59.8 K | 177.4 / 167.8 K |
| Aday 9 | 8.4° | 45.3 K | 56.9 / 71.9 K | 177.3 / 243.0 K |
| Aday 10 | 1.1° | 11.7 K | 58.9 / 62.5 K | 185.4 / 183.5 K |

Ortalama fark 11-84 K (medyan 32 K), en yüksek sıcaklık −66 ile +40 K arası sapıyor. İki neden var, ayrıştırılmadı: Güneş birkaç derece yükseklikteyken birkaç derecelik eğim güneş ışığını iki katına çıkarır ya da yarıya indirir (en yüksek sıcaklığın çoğunlukla düşük çıkması, eğimli adaylarda farkın büyümesi bununla uyumlu); 5 km ızgaranın karıştırdığı ufuk bir sırt noktasında Güneş'i fazla uzun (Aday 1, 4: en düşük sıcaklık 30-35 K daha soğuk) ya da kısa (Aday 2, 7: en yüksek sıcaklık 20-40 K daha sıcak) saklayabiliyor. Hangisinin ağır bastığı `python scripts/thermal_attribution.py --spice` ile ayrıştırılır (~2-5 dk): aynı noktalarda motor beş şekilde çalıştırılır (kendi ufku / ızgara ufku × eğimli / düz zemin, bir de ızgara ufku + 240 m'lik eğim haritası) ve her birinin motordan (kendi ufku, eğimli) farkı ölçülür. **Karar kuralı, çalıştırmadan önce yazıldı:** 240 m eğim haritası tarayıcıya ancak, onunla medyan hata bugünkünün yarısına ve 15 K'nin altına iniyorsa eklenecek. Sonuç `thermal_attribution.json`'a yazılır.

**Ayrıştırmanın sonucu (DE440, 11 nokta, medyan ortalama |ΔT|):** kendi ufku + düz zemin 26.7 K (yalnız eğimin etkisi), ızgara ufku + gerçek eğim 10.5 K (yalnız ufkun etkisi), ızgara ufku + düz zemin 32.2 K (tarayıcının eski hali), ızgara ufku + 240 m eğim haritası **14.8 K**. Geçerlilik kontrolü tuttu: betiğin motor sürümü `thermal.json`'ı her noktada 0.025 K içinde yeniden üretiyor. Kural sağlandı (32.2 → 14.8 K: yarısı 16.1'in ve 15 K'nin altında, 15 K sınırına yakın), bu yüzden eğim haritası eklendi. Eğim tek başına daha büyük etken; ama sırt noktalarında ufuk hâlâ baskın: Aday 1'de ızgara ufku Güneş'i 8325 yerine 63 saat gösteriyor ve hata 81 K'de kalıyor, Aday 4'te 46 K. 240 m bloğun normali bazen noktanın kendisininkinden epey farklı (Aday 9: 8.4° yerine 16.5°), bu yüzden E, C'den (gerçek eğim) kötü; bloklar arası karıştırma bunu azaltabilir ama sonucu görüldükten sonra seçilmiş olur, denenmedi.

**Kutup eğim haritası** (`engine/surface/slope_map.py`, `scripts/build_slope_map.py`, ~1-3 dk): 120 m haritanın 2 × 2 piksellik her bloğu için, `build_thermal`'ın `local_normal`'ının blok merkezindeki değeri; yerel doğu / kuzey bileşenleri int16 (0.002° çözünürlük) parçalar halinde (`web/public/data/slope_map_s/`, 80°'ye kadar, kutup başına 25.7 MB, ~8 s; `--min-lat 75` iki katı). Betik saklanan normalleri 300 rastgele noktada ve adaylarda yeniden hesaplananla karşılaştırır (sınır 0.01°, aşılırsa çıkış kodu 2). `web/tests/slope.check.mjs` tarayıcının çözümlemesinin Python'unkiyle aynı olduğunu (10⁻⁶° içinde) sınar; `tests/test_slope_map.py` normallerin `local_normal`'la birebir aynı olduğunu ve düzgün eğimli bir haritanın eğimini geri verdiğini. **Yeni kayıtlı kontrol** (`regolith.check.mjs` 4, veriyle çalıştırılmadan önce yazıldı): tarayıcı, eğim haritası ve ızgara ufkuyla, her adayda betiğin E sürümünü yeniden üretmeli: ortalama hata, en düşük ve en yüksek sıcaklık 0.5 K içinde. Sentetik haritada (iki taraf analitik efemeris) en düşük / en yüksek sıcaklıklar 0.1 K içinde tuttu. **Sonuç (DE440, LOLA): 11 adayın 11'i geçti**, hepsinde fark 0.02 K'den küçük (ör. Mons Mouton: hata 5.25 / 5.26 K, en düşük 62.8 / 62.8, en yüksek 194.9 / 194.9 K). Haritanın kendi kontrolü: saklanan normaller yeniden hesaplananlardan en fazla 0.0012° farklı (güney ve kuzey). Eğim haritası her noktada iyileştirmiyor: Aday 8 (10.9 → 13.8 K) ve 10 (11.7 → 12.4 K) biraz kötüleşiyor, Aday 9'da blok eğimi (16.4°) noktanınkinden (8.4°) büyük olduğu için en yüksek sıcaklık 276 K, motor 243 K. Medyan iyileşme kayıtlı ölçütle değerlendirildi; bu tek tek sapmalar sayfadaki uyarıda sayılarla duruyor.

Sonuç: tarayıcının sıcaklık hesabı düz zeminde motorla aynı, eğim haritasıyla kutupta medyan ~15 K, ama **sırt noktalarında hâlâ kaba**; sayfa bunu sayılarla yazıyor ve adaylar için Forecast'teki hesabı gösteriyor. Kutupta güneş saatleri ve iniş pencereleri daha sağlam sayılar (ızgara hatası yukarıda ölçülü). Düşük enlemlerde Güneş yüksek, birkaç derecelik eğimin etkisi küçük; orada Diviner ekvator kontrolü geçerli.

Tarayıcıdaki sıcaklıkta olmayanlar (sayfada yazılı): noktanın kendi ufku (kutupta 5 km ızgaradan karıştırılır), 80°'den düşük enlemlerde zeminin eğimi (düz alınır) ve çevredeki araziden gelen ışık ve ısı. Adaylar için üçünü de içeren hesap Forecast sayfasında. Kutupta güneşli saatlerde modelin Diviner'dan ~30 K soğuk çıktığı (aşağıda) burada da geçerli.

**CSV dışa aktarma** (`web/src/lib/csvExport.ts`, v0.18): sayfadaki sayılar iki dosya olarak indirilebilir. Saatlik seri: zaman (UTC), Güneş yükselimi / azimutu / o yöndeki ufuk, diskin ufkun üstündeki payı, Güneş'e dönük yüzeye düşen güneş ışığı (W/m²), Dünya yükselimi / azimutu / ufku, görünen DSN istasyonları, yüzey sıcaklığı. Olaylar: gündüzler, iniş pencereleri ve tutulmalar, zaman sırasıyla. Her dosyanın başındaki `#` satırları noktayı, dönemi, efemerisi, ufuk ve zemin türünü, iniş kuralını, varsayımları ve aynı görünümün linkini yazar; dosya sayfadan ayrılsa da nereden geldiği belli olur (pandas: `read_csv(..., comment="#")`). `web/tests/csv.check.mjs` dosyadaki her sayının sayfanın kendi hesabı olduğunu, saatlerin sıcaklık çalıştırmasıyla örtüştüğünü ve olay sayılarının sayfadakiyle aynı olduğunu sınar.

Sınırlar (sayfada yazılı): 75°'den düşük enlemler için ufuk şimdilik düz, iniş penceresi transfer ve yörünge düzlemini içermez (onlar Browse and plan'da), tutulmalar geometrik (atmosfer gölgeyi ~%2 genişletir).

## 3D görünüm

**3D view** sekmesinin ikinci sahnesi (**Landing region**) Griffin-1 bölgesini gerçek LOLA arazisiyle, Ay'ın eğriliğiyle ve tahmin dönemindeki herhangi bir saatin Güneş'iyle gösterir (raw WebGL2, ek kütüphane yok). İki kamera var: **Overview** (bölgenin üstünden, döndür / yakınlaştır / kaydır, araziye tıklayıp nokta seç) ve **Lander's eye** (seçilen noktada 2 m yükseklikten 360° bakış: ufuk, Güneş ve Dünya'nın ±15 günlük yolları, Dünya'nın evresi). Zaman kaydırıcısı ve "Play" ile bir Ay günü boyunca gölgelerin dağların üstünden geçişi izlenebilir; tahminin pencerelerine ve her adayın en iyi iniş anına tek tıkla gidilir. Tahmin haritasının katmanları (iniş sonrası güneş, enerji, eğim...) araziye kaplanabilir. Bağlantı (kamera, zaman, nokta, katman) adres çubuğunda saklanır.

**Gölgeler hesaplanır, boyanmaz.** GPU her harita hücresinden Güneş'e doğru ışın yürütür ve yol boyunca en yüksek arazi açısını bulur; yöntem `compute_horizon` ile aynı küresel geometri, aynı başlangıç mesafesi (180 m), aynı gözlemci yüksekliği (2 m). Sonra güneş diskinin arazinin üstünde kalan payı enerji bütçesindeki formülle hesaplanır, yani yarı gölgeler de fiziksel. Arazi üç halkadan oluşur: bölge 120 m (tam LOLA çözünürlüğü), 100 km'ye kadar 360 m, 250 km'ye kadar 1.2 km (blok ortalamaları). Ortadaki halka bilerek eklendi: 41 km'den sonrası doğrudan 1.2 km olunca uzaktaki tepeler düzleşiyor ve hata iki katına çıkıyordu.

**Sayfa kendini kontrol eder.** Açılışta, 11 noktada (Athena'nın iniş noktası ve ilk 10 aday) iniş dönemi boyunca 3 saatte bir, tarayıcının GPU'sundaki gölge hesabı motorun tam çözünürlüklü ufuk maskeleriyle (0.5° azimut, 250 km, 120 m adım) karşılaştırılır ve sonuç sayfada yazar. Aynı algoritmanın numpy hali (`engine/surface/scene3d.py::march_sun_clear`) testlerde `compute_horizon`'a karşı sınanır; sahne üretilirken de aynı karşılaştırma yapılıp terminale yazılır, böylece tarayıcının sonucu bununla kıyaslanabilir. Geliştirme sırasında sentetik bir arazide (gerçek LOLA verisi bu ortamda yoktu): aydınlık / gölge kararı %100 aynı, Güneş yüksekliği farkı medyan 0.003°, %95'lik dilim 0.015°; GPU ile numpy aynı sonucu veriyor. Gerçek arazideki sayılar sahneyi LOLA haritasıyla ürettiğinizde terminalde ve sayfada görünür. Kalan fark uzak halkaların kaba çözünürlüğünden.

**Ne gerçek, ne çizim:** Arazi, eğrilik, Güneş / Dünya yönleri, gölgeler, disk payı, Güneş ve Dünya disklerinin açısal boyutu ve Dünya'nın evresi gerçek; dikey abartma yok. Yüzey parlaklığı basit mat bir model (regolitin gerçek yansıması değil), gölgeler arazi görünsün diye çok az aydınlatılmış (gerçekte neredeyse siyah), Güneş'in etrafındaki parıltı görünürlük için. 120 m'den küçük şeyler (kaya, küçük krater) görünmez; 250 km'nin ötesinde Ay düz bir küre olarak çizilir. Lander's eye görünümünde motorun ufuk maskesi pembe çizgiyle arazinin üstüne çizilir; çizilen arazinin silüeti bu çizgiyle örtüşmeli.

### 3D yolculuk

**3D view** sekmesinin ilk sahnesi, bir görevi tek bir saat üzerinde baştan sona gösterir: park yörüngesi, TLI, Ay'a yolculuk, yörüngeye giriş (LOI), Ay yörüngesinde bekleme, düzlem değişikliği, iniş ve yere temas. Üç görev var: **IM-1** ve **IM-2** yeniden kurulmuş haliyle (gerçek TLI tarihi ve transit süresi, gerçek iniş anı için en küçük düzlem değişikliğini isteyen kutupsal yörünge, iniş gerçek anda; Validation sayfasındaki rekonstrüksiyon) ve **Griffin-1** kayıtlı tahminin ilk penceresinin en iyi fırlatmasıyla. Üç kamera: Dünya ve Ay (tüm yolculuk, Ay'ın kendi yolu), Ay'ın çevresi (yaklaşma hiperbolü, yörünge ve altında dönen Ay), uzay aracını takip. Oynatma "Auto" hızında olaylara yaklaşınca yavaşlar. Yeşil çizgiler o anda uzay aracını 10°'nin üstünde gören DSN istasyonlarıdır; Dünya'nın dönüşü motorun yer istasyonu modelinden gelir. Dünya ve Ay gerçek ölçekte.

**Neyin nereden geldiği** (`engine/mission/journey.py`):
- Park yörüngesi ve Ay'a yolculuk: motorun çözdüğü transfer, saklanan kontrollerden tam kuvvet modeliyle yeniden yayılır (transfer görünümüyle aynı yol).
- Ay yörüngesi: iniş analizinin kullandığı model, yani dairesel yörünge ve J2 düğüm kayması. Analiz uzay aracının yörünge üzerindeki konumunu (fazını) modellemediği için, çizim iniş anında aracı bölgenin üstüne getirecek faz düzeltmesini bekleme süresine yayar ve büyüklüğünü sayfada yazar (IM-1'de yörünge hareketinin ~%3'ü, diğerlerinde ~%1).
- Düzlem değişikliği: analiz tek bir anlık yanma sayar; çizim düzlemi son turda çevirir. Açı ve Δv analizinkiyle aynı (testte 0.02° içinde).
- İniş: **şematik.** Yörüngeden 15 km'ye inen yarım elips (analizin iniş modeli) ve bölgeye bir frenleme yayı; Δv'si analizin, yolu ve zamanlaması temsilidir.
- Ay'ın güney kutbu LOLA haritasından (~1.9 km bloklar), bu görünümde gölge düşürmeden aydınlatılır; gerçek gölgeler Landing region sahnesinde.

Gerçek görevler ara düzeltme ve faz yanmaları yaptı; bu yollar motorun modelidir, uçulan yörünge değildir. Sayfa bunu yazar.

## Regolit sıcaklıkları

`engine/surface/thermal.py`, Hayne vd. (2017) regolit modelinin bağımsız bir uygulaması (JGR Planets 122, [arXiv:1711.00977](https://arxiv.org/abs/1711.00977), Ek A ve Tablo A1). Yere doğru tek boyutlu ısı iletimi:

- yoğunluk ve temas iletkenliği derinlikle üstel artar (ρ 1100 → 1800 kg/m³, k 7.4·10⁻⁴ → 3.4·10⁻³ W/m/K, H = 0.06 m),
- taneler arası ışınım: k(T) = k_c [1 + χ (T/350 K)³], χ = 2.7,
- ısı kapasitesi sıcaklığın 4. derece polinomu (Hemingway vd. 1981),
- albedo geliş açısıyla artar: A(i) = 0.12 + 0.06 (i/45°)³ + 0.25 (i/90°)⁸ (kutupta Güneş hep yatay geldiği için önemli),
- yüzey: εσT⁴ = (1 − A) S cos i · f + k ∂T/∂z (ε = 0.95, S = 1361 W/m²), dipte Ay'ın iç ısı akısı 0.018 W/m².

Tüm sabitler makalenin standart değerleri, burada ayarlanmadı. Bizim kattığımız şey, güneş girdisi: efemerisin Güneş uzaklığı ve yönü, zeminin LOLA'dan eğimi (240 m) ve f, Güneş diskinin LOLA ufkunun üstünde kalan payı (enerji bütçesiyle aynı sayı). Sayısal yöntem: Hayne'deki gibi geometrik büyüyen ızgara (ilk katman diurnal deri derinliğinin onda biri), kararlılık sınırlı açık zaman adımı, yüzey sıcaklığı enerji dengesinden Newton yöntemiyle; derin katmanlar hızlandırılmış dengeleme ile (her geçişten sonra Aitken ekstrapolasyonu) bir yıl boyunca ısındırılır.

**Doğrulama:** Ekvatorda düz zemin için LRO Diviner'ın tipik değerleri (Vasavada vd. 2012, Hayne vd. 2017 içinde): öğlen ~385 K, gece yarısı 101 K, gün doğumundan hemen önce 95 K. Model: 385.2 / 101.9 / 95.6 K (5 K tolerans). Testler ayrıca kesin sonuçlara karşı sınar: sabit özellikli toprakta günlük dalga deri derinliğiyle sönümlenir (%0.3), öğlen ışınım dengesi (1.5 K), bir Ay günü boyunca emilen + iç ısı = yayılan (%1), ızgara ve zaman adımı yarıya inince sonuç 1 K'den az değişir.

**Araziden gelen ışık ve ısı (çoklu yansıma)** (`engine/surface/radiosity.py`): Bir nokta doğrudan Güneş'in yanında gördüğü arazinin yansıttığı güneş ışığını ve yaydığı kızılötesini de alır; gölgede tek ısı kaynağı budur. İki araç:
- **Yüzey parçaları arası radyozite:** görüş faktörleri (F_ij = cos θ_i cos θ_j A_j / π r²) ve tüm yansımalarla denge: B = α(E + FB) görünür ışık için, W = (1 − α)(E + FB) + εFW kızılötesi için (W = εσT⁴). Küresel kase biçimli bir kraterin gölgesindeki sıcaklığın kapalı formülüyle (Ingersoll, Svitek & Murray 1992) sınanır: 170.44 K'e karşı 170.76 K (%0.19; ε = 1 ile %0.007, kalan fark formülün kızılötesi soğurmayı ele alış biçimi).
- **Tek nokta için yön örneklemesi** (adaylarda kullanılan): noktanın araziyi gördüğü her yön (LOLA ufkunun altında, kendi eğik yüzeyinin düzleminin üstünde) arazideki çarpma noktasına kadar izlenir; o noktanın kendi ufkuyla güneş alışı ve kendi sıcaklığı (aynı regolit modeliyle) hesaplanır, geri gönderdiği ışık ve ısı ağırlıklarla (cos θ dΩ / π) toplanır. Tek yansıma: arazinin başka araziden aldığı ışık sayılmaz; bunun eksik bıraktığı pay, görüş payı f olan bir kase için `single_bounce_ratio` ile verilir (sentetik arazideki adaylarda en fazla ~%2.4). Aynı kase üzerinde, 120 m'lik haritada, gölgedeki zemine gelen akı tek yansımalı kapalı formülden %1.5 sapar.

Sonuç (sentetik arazide; gerçek değerler LOLA ile): sırt ve plato üzerindeki adaylar gökyüzünün ancak %0.01–2.4'ünde arazi görür ve gece de çevreleri karanlıkta olduğu için en düşük sıcaklıkları <1 K değişir. Çukurdaki bir noktada (gökyüzünün %2.3'ü arazi, çevresi aydınlıkken kendisi gölgede) en düşük sıcaklık 31 K'den 41 K'e çıktı. Yani bu terim, gölgede kalan yerlerde önemli, güneşli sırtlarda değil.

**Forecast sayfası:** referans nokta ve ilk 10 aday için iniş dönemindeki yüzey sıcaklığı, en iyi iniş anından sonraki 14 günün en düşük / en yüksek değeri ve 150 K altında geçen saatler; karşılaştırma için referans noktanın "düz zemin, arazi yok" hali (aradaki fark eğimin ve arazinin etkisi). Tablo arazinin görüş payını ve "sadece Güneş" ile en düşük sıcaklığı da gösterir. Bu analiz tahmin kaydından sonra yapıldı; kaydın parçası değildir.

**Kutupta Diviner'a karşı** (`scripts/diviner_polar_check.py`, `engine/validation/diviner_pcp.py`): Ekvator kontrolü üç tipik sayı kullanır; asıl önemli olan kutup. Diviner'ın güney kutbu kümülatif ürünleri (Williams vd. 2019, PDS Geosciences) poleward 80° G için her 240 m'lik hücrenin Temmuz 2009 - Şubat 2019 arasındaki ortalama bolometrik sıcaklığını yerel saate (96 dilim) ve mevsime (yaz / kış) göre verir. Dosyalar ~200 MB ve sabit uzunluklu satırlardan oluştuğu için hepsi indirilmez: hücre, HTTP aralık istekleriyle ikili arama yapılarak okunur: açık tutulan tek bağlantı üzerinden nokta başına ~16 küçük istek, arama son 256 satıra inince tek istekte blok okuma, aynı dosyadaki noktalar okunanları paylaşır, aynı anda 4 dosya. Başarısız istekler artan beklemeyle 6 kez denenir. Dosyanın sıralaması ve x/y projeksiyonu varsayılmaz, örnek satırlardan çıkarılıp kontrol edilir; tutmazsa betik çalışmayı reddeder. Referans nokta, ilk 10 aday ve IM-1'in Malapert A noktası için her 4. yerel saat dilimi ve iki mevsim okunur (48 dosya, `data/cache` içinde önbelleğe alınır). Model aynı noktalarda aynı yıllar boyunca (saatlik, DE440, LOLA ufku ve eğimi, bir yıllık ısınma) çalıştırılır ve aynı yerel saat / mevsim dilimlerine ışınım ağırlıklı (T = ⟨T⁴⟩^¼) ortalanır. **Geçme ölçütü, hiçbir Diviner değeri okunmadan betiğe yazıldı:** tüm noktalar, mevsimler ve dilimler üzerinde medyan |model − Diviner| ≤ 10 K. Sonuç ne çıkarsa Validation sayfasında gösterilir. Modelde olmayanlar: 240 m'den küçük pürüzlülük (bir hücrede aydınlık ve gölge yamaları; alçak Güneş'te ölçülen bolometrik sıcaklığı yükseltir) ve araziden gelen ışık / ısı (bu noktalarda < 2 K).

**Sonuç (DE440, LDEM_75S_120M, 12 nokta, 414 dilim): FAIL.** Medyan |model − Diviner| 21.4 K (ölçüt 10 K). IM-2'nin Mons Mouton noktası 5.0 K ile ölçütün içinde; IM-1'in Malapert A noktası 14.4 K (yanlılık −4 K); adaylar 13-48 K. Ölçüt değiştirilmedi, sonuç Validation sayfasında kalan kontrol olarak duruyor.

**Kontrolden sonra: fark nereden geliyor** (veri görüldükten sonra yapılan, kaydın parçası olmayan analiz). Aynı karşılaştırma, model ve Diviner'ın noktayı aydınlık (> 150 K) mı karanlık (< 100 K) mı gördüğüne göre bölündüğünde:

| Model ve Diviner | Dilim | Model − Diviner (medyan) |
|---|---|---|
| İkisi de gölgede / gecede | 175 | −2.5 K |
| İkisi de güneşte | 115 | −28.7 K |
| Model gölgede, Diviner'ın hücresi sıcak (> 120 K) | 39 | −85.6 K |
| Model güneşte, Diviner'ın hücresi soğuk | 0 | – |
| Arada (gün doğumu / batımı, kısmi gölge) | 85 | −50.2 K |

Gece ve gölgede model Diviner'ı yakından izliyor; yani regolitin depoladığı ısı ve gece soğuması doğru (güç bütçesinde ısıtıcı yükünü belirleyen kısım). Fark güneşle geliyor: ikisi de güneşteyken model daha soğuk (Güneş'in daha yüksek olduğu 80° G'deki Malapert A'da daha az), ve 39 dilimde Diviner'ın hücresi ısınmışken modelin noktası hâlâ arazinin arkasında; tersi hiç yok. Olası açıklamalar: kısmen aydınlık bir hücre (sıcak kısmı ışınım ağırlıklı ortalamaya hâkim olur), 120 m'lik haritadan küçük pürüzlülük, ekvatorda uydurulmuş albedo yasası. Hiçbiri ayarlanmadı.

`python scripts/diviner_polar_diagnose.py --spice` (kontrolden sonra, ~15-25 dk) ilk açıklamayı sınar: Diviner'ın sayısı 240 m'lik hücrenin ışınım ağırlıklı ortalaması, kayıtlı kontrol ise modeli tek noktada çalıştırdı. Teşhis betiği her noktanın kendi hücresini (tüm dosyalar içinde noktaya en yakın olan; bir dosyada o hücrede veri yoksa kontrol komşu hücreyi kullanmıştı, o dilimler bu karşılaştırmaya alınmaz) ve merkezini arşivden okur, okunan sıcaklığın önbellektekiyle aynı olduğunu kontrol eder, modeli hücreye yayılmış 3 × 3 noktada (80 m arayla, her biri kendi LOLA ufku ve eğimiyle) çalıştırır ve aynı şekilde ortalar. Serbest parametre yok. Adil olsun diye nokta modeli de aynı dilimler üzerinde ayrıca verilir. Sonuç `diviner_polar_diagnostics.json`'a yazılır ve Validation sayfasında kayıtlı sonucun altında, ayrı olarak gösterilir; kontrolün sonucunu değiştirmez.

**Teşhisin sonucu (DE440, LDEM_75S_120M): bu açıklama tutmadı.** Her noktanın kendi hücresinin kullanıldığı 410 dilimde medyan |model − Diviner| nokta modeliyle 21.7 K, hücreye yayılmış modelle 23.5 K. Güneşte −29.0 → −32.5 K, "model gölgede, Diviner sıcak" −85.6 K (39 dilim) → −73.5 K (34 dilim), gece / gölge −2.5 → −2.0 K. 120 m'lik haritanın gösterebildiği hücre içi farklar açığı kapatmıyor. Geriye haritanın çözemediği şeyler kalıyor: 120 m'den küçük pürüzlülük, ekvatorda uydurulmuş albedo yasası ve gün doğumu / batımında ufkun bir kesri derece kadar yanlış olması. Bunlar sınanmadı.

**Projeye etkisi:** Gece ve gölge sıcaklıkları (güç bütçesinde ısıtıcı yükünü belirleyen kısım) Diviner'la uyumlu. 85° G'de güneşli saatlerin sıcaklıkları büyük olasılıkla ~30 K düşük tahmin ediliyor. Griffin-1 tahmininin sıralaması güneş ışığına ve araziye dayanıyor, sıcaklığa değil; bu sonuçtan etkilenmiyor.

**Güç bütçesi** (Forecast sayfası, `web/src/lib/power.ts`): Astrobotic Griffin'in güç sistemini yayımlamadı, bu yüzden bu bir tahmin değil hesaplayıcı. Kullanıcı panel alanını, verimi, montajı (Güneş'e dönen dikey, sabit dikey, yatay), batarya kapasitesini ve kullanılabilir payını, güneşte ve gölgede çekilen gücü girer; motor noktaya düşen güneş ışığını verir: Güneş uzaklığından S/r², Güneş diskinin LOLA ufkunun üstündeki payı ve Güneş yükselimi, en iyi iniş anından itibaren 2 saatlik adımlarla (`build_thermal` bunları `dni_w_m2` ve `sun_el_deg` olarak yazar). Batarya doluluğu adım adım izlenir; kullanılabilir sınırın altına inerse "dayanamaz" ve zamanı gösterilir. Gerekli en küçük batarya (bu panellerle) ve en küçük panel (bu bataryayla) aynı simülasyon üzerinde ikiye bölme ile bulunur. Batarya / kablo kayıpları yok, gölgede ısıtıcı yükü kullanıcının girdisi (yalıtıma bağlı; zemin sıcaklığı sadece ipucu). Varsayılan değerler genel, Griffin'in değil. `build_thermal` ayrıca her nokta için en iyi iniş anında Güneş'in arazinin üstünde olup olmadığını kontrol eder: tahminin iniş kuralı bunu şart koşar, tutmazsa tahmin ve sıcaklık çalıştırması farklı arazi / ufuk ayarlarıyla yapılmış demektir ve hem çıktıda hem arayüzde uyarı verilir.

## Efemeris

- `AnalyticEphemeris`: dosyasız; Ay yönelimi tam IAU 2009 modeli (DE440'tan ~0.03°), Ay yörüngesi dairesel (demo için).
- `SpiceEphemeris`: JPL DE440 + MOON_PA. Sunulacak sonuçlar için bu.
- `CachedEphemeris`: saatlik Hermite tablosu (format v2: Ay dönüşü dahil). Ay konumu ~1 cm, meridyen 0.000001° doğrulukta; transfer başına süreyi yaklaşık yarıya indirir. `.npz` olarak paylaşılabilir:

```
python scripts/build_ephemeris_cache.py --spice --start 2025-11-01 --end 2026-12-31
python -m api.server --ephem-cache data/cache/ephem_spice_2025-11-01_2026-12-31.npz
```

## API

`python -m api.server [--port 8000] [--workers 2] [--spice | --analytic] [--ephem-cache ...]`

| Uç nokta | |
|---|---|
| `GET /api/health` | durum, efemeris |
| `GET /api/sites` | bölge kataloğu, varsayılan kısıtlar |
| `POST /api/transfers` | `{tli_utc, tof_days, family, lunar_inc_deg, periselene_alt_km}` → `{job_id}` |
| `GET /api/jobs/<id>` | `queued / running / done / error`; sonuçta transfer, yörünge ve tüm bölgeler için iniş analizi |
| `POST /api/trajectory` | veritabanındaki bir transferin yolunu kontrollerinden yeniden hesaplar |

Bir transfer tasarımı ~4-7 sn sürer; işler ayrı süreçlerde paralel koşar.

## Doğrulama

Arayüzün **Validation** sekmesi (`http://localhost:8000/#validation`) aşağıdaki doğrulamaların hepsini ve sıcaklık modelinin kontrollerini bir arada gösterir.

**1. NASA Ames karşılaştırması (DE440, Genova vd. 2024 penceresi):** 195/195 transfer yakınsadı; LOI bandı 805-982 m/s (NASA ~797-980). Aylık minimumlar NASA grafiğinden 0-2 gün uzakta (taramamız 3 günde bir). 5-13 Ocak 2026 yoğun taramasında minimum **800.7 m/s** (TLI 10 Ocak, 5.0 gün), NASA'da ~797 m/s: fark %0.5. NASA veriyi değil grafiği yayımladığı için referans değerler grafikten okundu (tarih ±1.5 gün, Δv ±3 m/s), `engine/validation/nasa_reference.py`.

**2. Uçmuş görevlerin geriye dönük testi** (`engine/validation/retrodiction.py`, `scripts/build_validation.py`). Araca sadece bölge, fırlatma ve LOI zamanları ve yörünge irtifası verilir; inişin ne zaman ve nasıl olduğu verilmez. Kaynaklı görev verisi `engine/validation/missions.py` içinde.

IM-1 Odysseus (Şubat 2024, Malapert A), JPL DE440 ile:

| Soru | Araç | Gerçek |
|---|---|---|
| Ocak 2024 fırlatma penceresi | 7-20 Ocak (14 gün) | 12-14 Ocak (ilk plan) |
| Şubat 2024 fırlatma penceresi | 6-19 Şubat (14 gün) | 14-16 Şubat, 15'inde fırlatıldı |
| 15 Şubat fırlatmasından iniş | **22 Şubat 22:48 UTC** | 22 Şubat 23:24 UTC (36 dakika fark) |
| İnişte Güneş | 10.5°, yükseliyor, gün doğumundan 6.5 gün sonra | |
| İnişten sonra gün ışığı | 9.3 gün (düz ufuk) | 6 gün çalıştı (yan yatmıştı) |
| LOI Δv (gerçek TLI + 6.35 günlük transit, 92 km) | 824 m/s | 800 m/s (%3.0 fark) |

IM-2 Athena (Mart 2025, Mons Mouton), JPL DE440 ile:

| Soru | Araç | Gerçek |
|---|---|---|
| Fırlatma penceresi | 22 Şubat - 6 Mart (13 gün) | 26 Şubat - 1 Mart, 27'sinde fırlatıldı |
| 27 Şubat fırlatmasından iniş, düz ufukla | 4 Mart 20:04 UTC | 6 Mart 17:29 UTC (1.9 gün erken) |
| 27 Şubat fırlatmasından iniş, LOLA arazisiyle | 7 Mart ~17:54 UTC | 6 Mart 17:29 UTC (1.02 gün geç) |
| İnişte Güneş | 2.5°, yükseliyor, gün doğumundan 2.4 gün sonra | |
| Gerçek varışla gerçek iniş anı | inilebilir: kutupsal yörüngede 52 m/s, 92°'de 4 m/s düzlem değişikliği | |
| LOI Δv | 832 m/s | yayımlanmadı |

Bulgular:

- **Pencereleri aydınlatma belirliyor.** Kutup bölgesi her ay ~2 hafta iniş için uygun, ~2 hafta değil; üç gerçek pencerenin üçü de tahmin edilen pencerelerin içinde.
- **Yörünge eğimi serbest bir tasarım değişkeni.** Tam kutupsal (90°) bir yörüngeyle 15 Şubat fırlatmasından iniş mümkün değil, çünkü Malapert A yörüngeden 8.6° uzakta kalıyor (245 m/s). Yörünge birkaç derece eğilince (80-86° veya 94-100°) bölge gerçek iniş anında yer izinin altına giriyor ve LOI Δv'si 2 m/s'den fazla değişmiyor. Bu yüzden geriye dönük test 80-100° arasını tarıyor.
- **13 görev kontrolünden 12'si geçiyor.** Geçmeyen IM-2'nin iniş günü. Düz ufukla araç 1.9 gün erken iniyordu; LOLA arazisi eklenince sapma yön değiştirdi, artık 1.02 gün geç, yani bir günlük sınırı ~25 dakikayla aşıyor. Arazi bölgede Güneş'i biraz geciktiriyor, araç da en ucuz seçeneği aldığı için bir sonraki güne kayıyor. Eşiği sonuca göre ayarlamadık; kontrol başarısız olarak kalıyor. Gerçek iniş anı araziyle de inilebilir bir an. IM-1 LOI kontrolü %3 sınırını kıl payı geçiyor (%2.97).
- Analitik efemerisle aynı test 11/13 veriyor (LOI %5 sapıyor). Fark, Ay'ın gerçek eliptik yörüngesinden geliyor.

**Blue Ghost Mission 1 (Firefly, Mart 2025, Mare Crisium):** ilk kutup dışı geriye dönük test (`engine/validation/missions.py`, `BG1`). Araca verilenler yine yalnızca yayımlanmış olanlar: fırlatma (15 Ocak), TLI günü (8 Şubat; saati yayımlanmadı, öğlen UTC ±12 saat varsayıldı), Ay yörüngesine giriş (14 Şubat 01:53 UTC), ~100 km yörünge ve Firefly'ın LOI'de duyurduğu 16 günlük yörünge kontrol süresi (araca 20 gün bekleme izni verilir; kuralı yine en erken uygun anı seçer). Yörünge eğimi yayımlanmadığı için 22-158° taranır. Yakın yüz kuralı: Güneş ufkun 3-20° üstünde ve yükseliyor, Dünya en az 2°. Fırlatma penceresi sorusu bu görevde anlamsız (fırlatma ile TLI arasında 25 gün Dünya yörüngesi); sayfada bu açıkça yazılı ve o kontrol eklenmez. Yeni bir kontrol: **gün batımı.** Firefly'ın bildirdiği 346 saatlik yüzey gün ışığı ve son verinin "gece başladıktan 5 saat sonra" gelmesi gerçek gün batımını 16 Mart ~18:30 UTC (±20 dk) olarak verir; düz ufukla tahmin edilen gün batımı 3 saat içinde olmalı (ölçüt ilk çalıştırmadan önce yazıldı: hesaba katılmayan 1°'lik ufuk bu enlemde gün batımını ~2 saat kaydırır). `python scripts/build_validation.py --spice --missions blue-ghost-1` (~15-25 dk). **Sonuç (DE440): 6 kontrolden 5'i geçiyor.** Gerçek inişte Güneş 3.4° ve yükseliyor, yerel gün doğumundan 7 saat sonra (yakın yüz kuralının alt sınırı 3°); Dünya 25.7°; gerçek iniş anı, kurulan varıştan 23 m/s düzlem değişikliğiyle inilebilir (en uygun eğim 62°, sonradan seçilmiş); gün batımı tahminimiz 20:13 UTC, gerçek ~18:30 (+1.7 saat, sınır 3 saat; düz ufuk varsayımıyla tahminin geç çıkması batıdaki araziyle uyumlu ama sınanmadı). **Kalan kontrol: aracın TLI gününden kendi seçtiği iniş** 3 Mart 18:19 UTC, gerçekten 1.4 gün geç; ölçüt 1 gündü, FAIL olarak kalıyor. Sonradan teşhis (kontrolü değiştirmez): TLI günü taraması 4-7 günlük transferleri ve 30° arayla 5 yörünge eğimini dener ve en az Δv'li seçeneği alır; yakın yüzdeki bir bölge için yörünge düzleminin bölgenin üstünden geçme zamanı eğime çok bağlı, bu kaba ızgarada en ucuz seçenek bir sonraki geçişe (3 Mart) düşüyor. Gerçek transfer süresi ve 4° arayla taranan eğimlerle, en uygun eğimde ilk iniş fırsatı 2 Mart 07:43 UTC, gerçek inişten 51 dakika önce; ama bu eğim sonuç bilinerek seçildiği için kontrol yerine geçmez.

**3. Diviner kutup karşılaştırması:** yukarıda, Regolit sıcaklıkları bölümünde. `python scripts/diviner_polar_check.py --spice` (ağ gerekir, ~5-10 dk, ~15 MB trafik). Bağlantı koparsa çökmez: okunanlar `data/cache/diviner_pcp_points.json`'a kaydedilir, aynı komut kalan dosyalardan devam eder (sorun sürerse `--workers 2`).

**4. Test paketi:** `pytest` (veya `python tests/run_all.py`): 99 test, DE440 kuruluyken hepsi geçiyor (kurulu değilse 3'ü atlanır).

| Test | Ne kanıtlıyor |
|---|---|
| İki cisim periyot kapanışı, enerji < 1e-11 | integratör doğruluğu |
| Zonal ivme = −∇U, Ay zonal alanında enerji korunumu | harmonik formülleri (J2-J7) |
| J2 düğüm gerilemesi, analitik formülle %2 içinde | dinamik fiziksel olarak doğru |
| Üçüncü cisim gelgit limiti, SRP, kuvvet bütçesi toplamı | kuvvet modelleri ve birleştirici |
| Event zamanlamaları, ileri-geri hata | event tespiti, sayısal kararlılık |
| Shooting (Newton + LM), eksik belirli problem, active-set | hedefleme katmanı |
| B-plane geometrisi, konik tahmin, tam TLI → LOI | görev zinciri uçtan uca |
| Önbellek: düğümlerde birebir, < 1 m, kaydet/yükle, transfer sonucu değişmiyor | efemeris önbelleği |
| IAU dönüşü ortonormal, yıldız günü, Ay'ın aynı yüzü Dünya'ya dönük | Ay yönelimi |
| Güneş-altı nokta 90°, uzak tarafta Dünya hep ufkun altında, gün doğumu 29.53 günde bir | yüzey geometrisi |
| Planlanmış şafak fırsatını buluyor, başarısızlık sebepleri doğru | iniş analizi |
| IM-1/IM-2 inişinde Güneş alçak ve yükseliyor; IM-2 varışı gerçek iniş anında inebiliyor; pencere gruplama | geriye dönük test |
| Sentetik LOLA ızgaraları: etiket okuma, projeksiyon yönü, düz kürede ufuk = eğim açısı, bilinen dağ doğru yönde ve yükseklikte, arazi gün doğumunu geciktiriyor, iki azimut hesabı birbirini tutuyor | arazi |
| Dünya dönüşü (ekinoks öğlesinde Güneş'in konumu), DSN'nin Ay'ı görme oranı, (SPICE varsa) IAU_EARTH ile karşılaştırma, enerji ve gölge süresi | yer istasyonu, enerji |
| Görev kaydı (duyurulan / varsayılan ayrı), 5 gün güneş şartı, iniş anı kuralları, eğim, sıralama, kayıt özetinin değişikliği yakalaması | tahmin |
| 3D sahne: harita kesitleri ve blok ortalamaları, projeksiyon, GPU'daki ışın yürütmenin numpy hali `compute_horizon`'a karşı (tam çözünürlükte medyan < 0.01°, kaba dış halkalarla < 0.03°), erken çıkışın sonucu değiştirmemesi | 3D gölgeler |
| 3D yolculuk: süreklilik ve sıra, Ay yörüngesi analizin modelinde (yarıçap, düzlem değişikliği açısı ve Δv'si analizle aynı, faz düzeltmesi küçük), yere temas bölgede ve iniş anında (< 1 m), yönelim kuaternionları | yolculuk |
| Regolit ısı modeli: Diviner ekvator sıcaklıkları (±5 K), günlük dalganın deri derinliğiyle sönümü, öğlen ışınım dengesi, bir Ay günü boyunca enerji korunumu, ızgara / zaman adımı yakınsaması | sıcaklık |
| Araziden ışık ve ısı: kase krater ağı tüm güneşi yakalıyor, küre görüş faktörü f, radyozite Ingersoll formülüyle (ε = 1: %0.5, ε = 0.95: %1), haritadaki kasede tek nokta örneklemesi tek yansımalı formülle (%6), dağınık albedo | çoklu yansıma |
| Diviner kutup dosyası okuyucu: sentetik tabloda satır biçimi, sıralama ve projeksiyonun örnek satırlardan bulunması, ikili aramanın doğru hücreyi bulması, veri olmayan yerde "yok" demesi; gerçek HTTP üzerinden, bağlantı koparan ve 503 dönen bir sunucuyla okumanın yine aynı sonucu vermesi, tek bağlantının yeniden kullanılması, aralık isteğini yok sayan sunucunun reddedilmesi; hücrenin kendi x/y'sinin okunması ve projeksiyonun tersinin enlem/boylamı geri vermesi | Diviner okuma |
| Gerçek HTTP ile tasarım işi, doğrulama hataları, klasör dışı erişim engeli | API |
| (SPICE varsa) önbellek ve IAU modeli DE440'a karşı | gerçek veriyle |

## Yol haritası

1. ~~Motor çekirdeği, efemeris, hedefleme, doğrulama~~
2. ~~TLI → LOI tasarımcısı, SPICE, efemeris önbelleği~~
3. ~~İniş bölgeleri, aydınlatma, Dünya görünürlüğü, iniş fırsatı analizi~~
4. ~~Veritabanı hattı, canlı API, arayüz~~
5. ~~Doğrulama sayfası, IM-1/IM-2 geriye dönük testi, görev planlayıcı (kayma toleransı, tersine sorgu)~~
5b. ~~Griffin-1 için kayıtlı tahmin: zaman ve bölge uygunluk haritası~~
5c. ~~DSN yer istasyonu görünürlüğü, kutupta enerji bütçesi, paylaşılabilir planlayıcı linki~~
5d. ~~3D görünüm: gerçek arazi, GPU'da motorla aynı gölge hesabı, astronot kamerası, motora karşı kendi kendini kontrol~~
5e. ~~3D yolculuk: IM-1, IM-2 ve Griffin-1, fırlatmadan yere temasa tek saat, DSN bağlantıları~~
5f. ~~Regolit sıcaklık modeli (Hayne vd. 2017), Diviner'a karşı doğrulama, adaylarda yüzey sıcaklığı~~
5g. ~~Araziden yansıyan ışık ve kızılötesi: radyozite (Ingersoll 1992 ile sınanmış) ve adaylar için tek yansımalı yön örneklemesi~~
5h. ~~Güç bütçesi hesaplayıcısı; regolit modelinin güney kutbunda Diviner ölçümleriyle karşılaştırılması (ölçüt önceden sabitlendi)~~
5i. ~~Anywhere: Ay'ın her noktasında zemin sıcaklığı ve güç bütçesi, tarayıcıda (motorla 10⁻¹³ K içinde aynı model)~~
6. ~~Arazi: LOLA ufuk maskeleri (kutup bölgelerinde gerçek aydınlatma)~~; sırada yüzey eğimi ve iniş elipsi
7. Eliptik / donmuş yakalama yörüngeleri, GRAIL tam gravite alanı
8. Yakalama yörüngesini 30 gün boyunca tam modelle propagate etmek (düzlem kayması)

## Lisans

Kod: MIT ([LICENSE](LICENSE)). `web/public/fonts` içindeki yazı tipleri GUST Font License'a tabidir. Motorun okuduğu ya da türettiği veri ürünleri (JPL DE440, LRO LOLA ve Diviner) NASA ve JPL'in açık arşivlerinden gelir; kaynaklar yukarıdaki bölümlerde.
