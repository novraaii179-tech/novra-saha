<div align="center">

# 📡 NOVRA SAHA BOTU (NOVRA FIELD BOT)
### Türkiye Geneli Otonom Resmi Kamu Kurumu Haber & Duyuru Takip Motoru
**NOVRA A.İ. Ekosistemi — Versiyon 1.4.1**

[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![Firebase Firestore](https://img.shields.io/badge/Firebase-Firestore-FFCA28?style=for-the-badge&logo=firebase&logoColor=black)](https://firebase.google.com)
[![GitHub Actions](https://img.shields.io/badge/GitHub_Actions-Otonom_Tarama-2088FF?style=for-the-badge&logo=github-actions&logoColor=white)](https://github.com/Yasin0234/novra-saha/actions)
[![Kapsam](https://img.shields.io/badge/Kapsam-81_İl_&_922_İlçe-4CAF50?style=for-the-badge&logo=googlemaps&logoColor=white)](#)
[![Lisans: MIT](https://img.shields.io/badge/Lisans-MIT-orange.svg?style=for-the-badge)](LICENSE)

<br/>

<p align="center">
  <b>Türkiye'deki 81 il ve 922 ilçede</b> bulunan Valilik, Kaymakamlık, Belediye, Jandarma, Emniyet, MEB, Tarım ve Sağlık kurumlarının anlık haberlerini otonom tarayan, metin, yüksek çözünürlüklü görsel ve video ayrıştırması yaparak Firebase Firestore'a aktaran yapay zeka saha ajanı.
</p>

</div>

---

## 👥 Geliştirici Ekip (Authors & Maintainers)

Bu proje **NOVRA A.İ.** bünyesinde geliştirilmiş olup fikri mülkiyeti ve bakımı geliştiricilere aittir:

<div align="center">

| <a href="https://github.com/Yasin0234"><img src="https://github.com/Yasin0234.png" width="110px;" alt="Muhammed Yasin KORKUT"/><br /><sub><b>Muhammed Yasin KORKUT</b></sub></a><br />🚀 Kurucu & Baş Mimar | <a href="https://github.com/jibeymin"><img src="https://github.com/jibeymin.png" width="110px;" alt="Beyza KARAKAŞ"/><br /><sub><b>Beyza KARAKAŞ</b></sub></a><br />💡 Kurucu & Baş Mimar|
| :---: | :---: |
| [@Yasin0234](https://github.com/Yasin0234) | [@jibeymin](https://github.com/jibeymin) |

</div>

---

## 🎯 1. Amaç ve Çalışma Mantığı
Türkiye'deki **81 il ve 922 ilçede** bulunan tüm kamu kurumlarının anlık duyuru, basın bülteni ve haber akışlarını tek bir merkezden izlemek, yapay zeka analizine hazır hale getirmek ve otomatik sınıflandırmak amacıyla tasarlanmıştır.

### 🏛️ İzlenen Kamu Kurumu Ağı
* 🏛️ **Valilikler & Kaymakamlıklar:** T.C. İçişleri Bakanlığı İSAY Portalı (`.gov.tr`)
* 🛡️ **İl Jandarma Komutanlıkları:** Asayiş, operasyonlar, huzur uygulamaları, narkotik
* 🚓 **İl Emniyet Müdürlükleri:** Polis bültenleri, trafik kontrolleri, asayiş denetimleri
* 📚 **İl & İlçe Milli Eğitim Müdürlükleri (MEB):** Okul projeleri, LGS/YKS sınavları, seminerler, atamalar
* 🌾 **İl & İlçe Tarım ve Orman Müdürlükleri:** Çiftçi desteklemeleri, hasat, mera, hayvancılık, aşılama
* 🏥 **İl Sağlık Müdürlükleri:** Şehir hastaneleri, MHRS, aşı takvimleri, halk sağlığı duyuruları
* 🚨 **İl AFAD Müdürlükleri:** Deprem, fırtına, sel uyarıları, afet tatbikatları, toplanma alanları
* 🏙️ **Belediyeler:** Şehircilik, altyapı, çevre, sosyal yardımlar ve su kesintileri

---

## 🏗️ 2. Akış Mimarisi

```mermaid
flowchart TD
    A["Resmi Kurum Web Siteleri<br/>(81 İl Valiliği & 922 İlçe / Tüm Kamu Ağları)"] --> B{"RSS Var mı?"}
    B -- "Evet" --> C["RssService Engine<br/>(XML Parser & Media)"]
    B -- "Hayır" --> D["Dynamic HTML Scraper<br/>(JSoup / Headless Worker / BS4)"]
    C --> E["Medya & Metin Ayrıştırma<br/>(Yüksek Çözünürlüklü Görsel & Video & Temiz Metin)"]
    D --> E
    E --> F["İl / İlçe & Kategori Etiketleme<br/>(ASAYIS, EGITIM, TARIM, SAGLIK vb.)"]
    F --> G[("Firebase Firestore:<br/>saha_haberleri")]
```

---

## 🏷️ 3. Kategorilendirme Sistemi

Taranan haberler metin ve kurum analizinden geçirilerek anında etiketlenir:

| Kategori Kodu | Kategori Başlığı | Kapsam & İçerik |
| :--- | :--- | :--- |
| **`ASAYIS_GUVENLIK`** | 🛡️ Asayiş ve Güvenlik | Jandarma, Polis, Narkotik, Kaçakçılık, Tutuklama, Trafik, Huzur Uygulamaları |
| **`EGITIM`** | 📚 Eğitim ve Okul | MEB haberleri, Okullar, Öğretmen/Öğrenci, LGS/YKS, Burslar, Tübitak |
| **`TARIM_HAYVANCILIK`** | 🌾 Tarım ve Hayvancılık | Çiftçi destekleri, Hasat, Şap aşısı, Sulama, Tohum, Mera, Hayvancılık |
| **`SAGLIK`** | 🏥 Sağlık ve Tıp | Hastaneler, Doktor, Poliklinik, Aşı, Randevu, İl Sağlık Müdürlüğü |
| **`AFET_ACIL`** | 🚨 Afet ve Acil Durum | AFAD, Deprem, Sel, Fırtına, Yangın, Tatbikat, Meteorolojik Uyarılar |
| **`BELEDIYE_HIZMET`** | 🏙️ Belediye ve Şehircilik | Asfalt, Park/Bahçe, Altyapı, Su kesintisi, Sosyal yardımlar, Zabıta |
| **`RESMI_DUYURU`** | 📜 Resmi Duyuru ve İlan | Valilik ve Kaymakamlık genel emirleri, İhaleler, Personel alımı ilanları |
| **`KULTUR_SANAT`** | 🎭 Kültür, Sanat ve Turizm | Festivaller, Konserler, Tiyatrolar, Sergiler, Yarışmalar |
| **`GUNCEL`** | 📰 Güncel ve Diğer | Genel yerel kamu gelişmeleri |

---

## 🧹 4. Otomatik Temizlik & 2 Günlük TTL (Time To Live) Motoru

Sistemin yorulmaması, Firestore depolama kotasının korunması ve uygulamanın daima en güncel 48 saatlik veriye anında erişebilmesi için **çift katmanlı temizlik** uygulanır:

1. **Bot İçi Otonom Temizlik (`eski_haberleri_temizle`):**
   Bot her periyodik çalışmada (her 15 dakikada bir), `silinmeTarihi <= şu_an` olan 2 günü doldurmuş haberleri Firestore'dan batch delete ile otomatik siler.
2. **Firestore Yerleşik TTL Politikası:**
   Her belgeye eklenen `silinmeTarihi` alanı Google Cloud Firestore TTL mekanizmasına uygundur.

```json
{
  "id": "e2a1b9c...",
  "baslik": "İl Jandarma Komutanlığından Huzur ve Güven Operasyonu",
  "ilAdi": "Adıyaman",
  "ilceAdi": "Merkez",
  "kurumTipi": "JANDARMA",
  "kategori": "ASAYIS_GUVENLIK",
  "kategoriAdi": "Asayiş ve Güvenlik",
  "gorselUrls": ["https://.../buyuk/operasyon.jpg"],
  "kapakGorseli": "https://.../buyuk/operasyon.jpg",
  "olusturulmaTarihi": "SERVER_TIMESTAMP",
  "silinmeTarihi": "2026-10-16T15:10:00Z",
  "gecerlilikSuresiGun": 2
}
```

---

## 🚀 5. Kurulum ve Çalıştırma

### 1. Bağımlılıkları Yükleme
```bash
pip install -r requirements.txt
```

### 2. Parametreli Çalıştırma Seçenekleri

```bash
# 1. Rotasyonel Otonom Tarama (Günün saatine göre 10'arlı il grupları)
python saha_bot.py --rotasyon

# 2. Belirli bir ilin tüm kurumlarını tara (Örn: Adıyaman - Plaka 2)
python saha_bot.py --plaka 2

# 3. Sadece Jandarma ve Emniyet haberlerini tara:
python saha_bot.py --kurum-tipi jandarma
python saha_bot.py --kurum-tipi emniyet

# 4. Sadece Eğitim (MEB) haberlerini tara (örn: Adıyaman):
python saha_bot.py --kurum-tipi meb --plaka 2

# 5. Sadece Tarım ve Orman haberlerini tara:
python saha_bot.py --kurum-tipi tarim

# 6. Sadece Sağlık veya AFAD haberlerini tara:
python saha_bot.py --kurum-tipi saglik
python saha_bot.py --kurum-tipi afad

# 7. Sadece Süresi Dolan (2 Günden Eski) Haberleri Temizle:
python saha_bot.py --sadece-temizle

# 8. Özel Ömür Belirleyerek Tara (Örn: 3 günlük saklama süresi):
python saha_bot.py --plaka 2 --omur-gun 3

# 9. Dry-Run Modu (Firebase yerine yerel 'saha_haberleri_test.json' dosyasına yazar)
python saha_bot.py --plaka 2 --dry-run
```

---

## ⚙️ 6. GitHub Actions Otonom Entegrasyonu

Depo içerisindeki `.github/workflows/novra_saha.yml` workflow'u ile bot tam otonomdur:
* ⏱️ **Zamanlanmış (Cron):** Her 15 dakikada bir otomatik rotasyon ile 81 il kurumlarını periyodik tarar ve 2 günü aşan eski haberleri siler.
* 🎛️ **Manuel Tetikleme (Workflow Dispatch):** GitHub Actions panelinden tek tuşla `mod` (rotasyon, tek_il, hepsi) ve `kurum_tipi` (jandarma, meb, tarim, emniyet vb.) seçilerek istenen il anında taranabilir.
* 🔑 **Gizli Anahtar (Secret):** `FIREBASE_SERVICE_ACCOUNT` secret olarak tanımlanmalıdır.

---

## 📄 7. Lisans (License)

Bu proje [MIT Lisansı](LICENSE) altında lisanslanmıştır.  
Copyright (c) 2026 **[Muhammed Yasin KORKUT](https://github.com/Yasin0234)** & **[Beyza KARAKAŞ](https://github.com/jibeymin)**.
Tüm hakları saklıdır.
