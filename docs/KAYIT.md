# GitHub'a koyma ve Griffin-1 tahminini kayda geçirme

Amaç: tahminin Griffin-1 fırlamadan **önce** yapıldığını, bize güvenmek zorunda kalmadan
herkesin doğrulayabileceği bir kayıt. **Son tarih: 1 Kasım 2026** (tahminin taradığı ilk
fırlatma günü; Griffin "en erken Kasım 2026").

**Kanıt neden commit tarihi değil:** bir commit'in tarihi kendi bilgisayarımızın saatinden
gelir ve istenen tarihe ayarlanabilir; tek başına hiçbir şey kanıtlamaz. Bu yüzden kanıt,
saatini başkalarının tuttuğu üç kayıttan oluşur:

1. **GitHub Release:** oluşturulma zamanını GitHub'ın sunucusu yazar; Release'e eklenen
   `forecast.json` ve açıklamadaki SHA-256 değiştirilemez bir parmak izidir.
2. **archive.org kopyası:** Wayback Machine dosyanın o anki halini kendi saatiyle saklar,
   GitHub'dan bağımsız.
3. **(İsteğe bağlı) OpenTimestamps:** dosyanın özetini Bitcoin zincirine bağlar; hesap
   gerektirmez, kimseye güvenmeyi gerektirmez.

Dosyanın içindeki `sha256` neyin kaydedildiğini (tahminin içeriği), `git_commit` hangi kodun
ürettiğini söyler.

## 0. Public mi private mı: public

- Space Apps kodun paylaşılmasını istiyor; jüri depoya erişebilmeli.
- Ücretsiz GitHub hesabında GitHub Pages yalnız public depolarda çalışır.
- Kayıt herkesin doğrulayabilmesi için var; private bir depoda kimse doğrulayamaz.

Projede gizli bir şey yok (anahtar, şifre, kişisel veri); risk yalnızca yanlışlıkla eklenen
dosyalar ve commit'lerdeki e-posta adresi. Aşağıdaki adımlar ikisini de kapatır.

**Hesap güvenliği (bir kez):** GitHub hesabında iki adımlı doğrulamayı açın
(Settings → Password and authentication). Commit'lerde kişisel e-posta görünmesin:
Settings → Emails → **Keep my email addresses private** ve **Block command line pushes that
expose my email**; orada yazan `...@users.noreply.github.com` adresini kopyalayın.

## 1. Bir kez: depo ve site

1. Proje klasöründe (Windows komut satırı), önce son hal:

   ```
   cd web
   npm test
   npm run build
   cd ..
   python tests/run_all.py
   ```

2. https://github.com/new adresinde **public** bir depo açın (ör. `clps-lunar-browser`).
   README, .gitignore veya lisans eklemeyin; hepsi projede var.

3. Git'i hazırlayın ve göndermeden önce kontrol edin:

   ```
   git init -b main
   git config user.name "KULLANICI"
   git config user.email "NUMARA+KULLANICI@users.noreply.github.com"
   python scripts/prepush_check.py
   ```

   `prepush_check` yayınlanacak her dosyayı tarar: anahtar / şifre / token, bu bilgisayarın
   yolları (`C:\Users\...`), e-posta adresleri, 50-100 MB'tan büyük dosyalar, `web/dist`'in
   koddan eski olup olmadığı, tahmin dosyasının bütünlüğü. **FIX** satırı varsa önce onu
   düzeltin; **warning** satırlarını okuyun. Hiçbir şeyi değiştirmez.

4. İlk commit ve gönderme:

   ```
   git add .
   git commit -m "CLPS Lunar Mission Browser v0.19"
   git remote add origin https://github.com/KULLANICI/clps-lunar-browser.git
   git push -u origin main
   ```

   `.gitignore` çekirdekleri (`data/kernels`), LOLA haritalarını (`data/terrain`), önbelleği
   (`data/cache`), `.venv` ve `node_modules`'u dışarıda bırakır; arayüz (`web/dist`) ve
   veriler (`web/public/data`) bilerek depoya girer.

5. GitHub'da:
   - **Settings → Pages → Build and deployment → Source: GitHub Actions.** Her push'ta
     `.github/workflows/site.yml` testleri çalıştırır, tahminin değişmediğini kontrol eder
     ve siteyi `https://KULLANICI.github.io/clps-lunar-browser/` adresinde yayınlar.
     **Actions** sekmesinde yeşil tik görünmeli.
   - **Settings → Code security:** "Secret scanning" ve "Push protection" açık olmalı
     (public depolarda varsayılan olarak açık): biri yanlışlıkla bir anahtar gönderirse
     GitHub push'u durdurur.

## 2. Tahmini kayda geçirme

Tahmin, commit edilmiş kodla üretilmeli; böylece `git_commit` alanı onu üreten kodu gösterir.
Kod commit edilmemiş değişiklik içeriyorsa `build_forecast` uyarır (`git_code_dirty`).

```
git status                                   (temiz olmalı: "nothing to commit")
python scripts/verify_forecast.py            (eski dosyanın sha256'sını not edin)
python scripts/build_forecast.py --spice     (~25 dk, önbellekten devam eder)
python scripts/verify_forecast.py
```

- **Yeni sha256 eskisiyle aynıysa** tahminin içeriği değişmemiştir; yalnız `git_commit`
  eklenmiştir. Doğrudan 3. adıma geçin.
- **Farklıysa**, aday listesine bağlı veriler de yenilenmeli:

  ```
  python scripts/build_scene3d.py --spice
  python scripts/build_journeys.py --spice
  python scripts/build_thermal.py --spice
  python scripts/thermal_attribution.py --spice
  ```

Sonra:

```
python scripts/prepush_check.py
git add web/public/data
git commit -m "Griffin-1 forecast, registered before launch"
git push
```

## 3. Release (sunucu saatiyle kayıt)

GitHub'da **Releases → Draft a new release**:

- Tag: `griffin-1-forecast` (main'deki son commit'te oluşturun)
- Başlık: `Griffin-1 forecast (registered before launch)`
- Açıklama (`forecast.json`'un `meta` alanından):

  ```
  Registered: <meta.registered_utc>
  Engine: <meta.engine_version>, JPL DE440, LOLA LDEM_75S_120M
  Code commit: <meta.git_commit>
  SHA-256 of {mission, time, region}: <meta.sha256>
  Verify: python scripts/verify_forecast.py
  ```

- `web/public/data/forecast.json` dosyasını Release'e ek olarak yükleyin.

## 4. Bağımsız kopya (archive.org)

1. Release sayfasında commit numarasını alın ve dosyanın **o commit'e bağlı** adresini kurun:
   `https://raw.githubusercontent.com/KULLANICI/clps-lunar-browser/<commit>/web/public/data/forecast.json`
2. https://web.archive.org/save adresine bu adresi yapıştırıp **Save Page** deyin.
   Aynısını Release sayfası (`https://github.com/KULLANICI/clps-lunar-browser/releases/tag/griffin-1-forecast`)
   için de yapın.
3. Wayback'in verdiği iki bağlantıyı (`https://web.archive.org/web/2026.../...`) README'ye
   ve sunuma ekleyin.

**İsteğe bağlı, OpenTimestamps:**

```
pip install opentimestamps-client
ots stamp web/public/data/forecast.json
```

Oluşan `forecast.json.ots` dosyasını da commit edin. Birkaç saat sonra `ots upgrade` ile
tamamlanır; `ots verify` dosyanın o tarihten önce var olduğunu Bitcoin zinciriyle kanıtlar.

## 5. Sonra

Bundan sonra `forecast.json` **değiştirilmez**; her push'taki CI kontrolü değişirse kırmızıya
döner. Kod, site ve README değişmeye devam edebilir. Yeni bir tahmin gerekirse (ör. IM-3)
ayrı bir dosya ve ayrı bir Release olur.

Her push'tan önce: `python scripts/prepush_check.py`.
