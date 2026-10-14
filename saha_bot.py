"""
================================================================================
NOVRA A.İ. - Versiyon 1.4 Kapsamlı Proje
2. YENİ BOT: NOVRA SAHA (NOVRA FIELD BOT)
Hazırlayan: Muhammed Yasin KORKUT
Tarih: 14.10.2026

KAPSAM:
- Valilikler & Kaymakamlıklar (İçişleri Bakanlığı İSAY Portalı)
- Emniyet & Jandarma (Asayiş, Güvenlik, Huzur Operasyonları, Trafik)
- Milli Eğitim Müdürlükleri (MEB İl & İlçe Haberleri)
- Tarım ve Orman Müdürlükleri (Çiftçi, Hasat, Desteklemeler, Hayvancılık)
- Sağlık Müdürlükleri (Hastaneler, Poliklinikler, Aşı, Sağlık Uyarıları)
- AFAD (Deprem, Sel, Fırtına, Acil Durum & Tatbikatlar)
- Belediyeler (Şehircilik, Altyapı, Sosyal Hizmetler)

AKIŞ MİMARİSİ:
[ Resmi Kurum Web Siteleri ] (81 İl & 922 İlçe / Tüm Kamu Ağları)
             │
    [ RSS Var mı? ]
     /            \
   Evet          Hayır
    │              │
[ RssService Engine ]    [ Dynamic HTML Scraper ]
(XML Parser & Media)     (JSoup / Headless Worker / BS4)
            \             /
      [ Medya & Metin Ayrıştırma ]
      (Yüksek Çözünürlüklü Görsel, Video, Temiz Metin)
                  │
      [ İl / İlçe & Kategori Etiketleme ]
      (ASAYIS_GUVENLIK, EGITIM, TARIM_HAYVANCILIK, SAGLIK, AFET_ACIL vb.)
                  │
  [ Firebase Firestore: saha_haberleri ]
================================================================================
"""

import os
import sys
import json
import re
import html
import hashlib
import argparse
import urllib3
from urllib.parse import urljoin, urlparse, parse_qs
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from bs4 import BeautifulSoup
import feedparser

# Resmi kurum ve kamu sitelerindeki SSL sertifika hatalarını yoksay
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ----------------------------------------------------------------------
# 1. TEMEL YAPILANDIRMA & YARDIMCI TANIMLAR
# ----------------------------------------------------------------------
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 (compatible; NovraSahaBot/1.4; +https://novraai.com)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"
}

KOLEKSIYON_ADI = "saha_haberleri"

TURKCE_HARF_HARITASI = str.maketrans({
    "ç": "c", "Ç": "c",
    "ğ": "g", "Ğ": "g",
    "ı": "i", "I": "i", "İ": "i",
    "ö": "o", "Ö": "o",
    "ş": "s", "Ş": "s",
    "ü": "u", "Ü": "u",
    "â": "a", "Â": "a",
    "î": "i", "Î": "i",
    "û": "u", "Û": "u"
})

def turkce_slug(metin: str) -> str:
    """Türkçe metni web ve domain uyumlu temiz ASCII slug'a çevirir."""
    if not metin:
        return ""
    metin = metin.strip().translate(TURKCE_HARF_HARITASI).lower()
    metin = re.sub(r"[^a-z0-9]+", "-", metin)
    return metin.strip("-")

def id_uret(url: str) -> str:
    """Haber URL'sinden tekil ve deterministik hash kimliği üretir."""
    return hashlib.sha256(url.strip().encode("utf-8")).hexdigest()[:24]

# ----------------------------------------------------------------------
# 2. KURUM TİPLERİ VE KATEGORİ SİSTEMİ
# ----------------------------------------------------------------------
KATEGORI_TANIMLARI = {
    "ASAYIS_GUVENLIK": {
        "ad": "Asayiş ve Güvenlik",
        "kelimeler": ["asayis", "polis", "jandarma", "operasyon", "hapis", "tutukla", "uyusturucu", "kacak", "trafik", "huzur", "denetim", "silah", "ele gecirildi", "yakalandi", "suc", "gozalti", "asayis bulteni", "emniyet mudurlugu", "jandarma komutanligi"]
    },
    "EGITIM": {
        "ad": "Eğitim ve Okul",
        "kelimeler": ["okul", "ogrenci", "ogretmen", "meb", "milli egitim", "sinav", "burs", "universite", "egitim", "kutuphane", "derslik", "lgs", "yks", "karne", "tatil", "seminer", "tubitak", "ders"]
    },
    "TARIM_HAYVANCILIK": {
        "ad": "Tarım ve Hayvancılık",
        "kelimeler": ["tarim", "ciftci", "hasat", "sulama", "tohum", "hayvancilik", "orman", "mera", "sap", "asi", "destekleme", "uretim", "seracilik", "fidan", "zirai", "gubre", "toprak", "rekolte"]
    },
    "SAGLIK": {
        "ad": "Sağlık ve Tıp",
        "kelimeler": ["hastane", "saglik", "doktor", "asi", "hemsire", "randevu", "tibbi", "tedavi", "poliklinik", "kan bagisi", "mhrs", "acil servis", "ilac", "halk sagligi", "ameliyat", "ambulans", "sehir hastanesi"]
    },
    "AFET_ACIL": {
        "ad": "Afet ve Acil Durum",
        "kelimeler": ["afad", "deprem", "sel", "firtina", "yangin", "heyelan", "tahliye", "tatbikat", "meteoroloji", "saganak", "uyari", "kar yagisi", "cig", "siren", "kurtarma", "cadir"]
    },
    "BELEDIYE_HIZMET": {
        "ad": "Belediye ve Şehircilik",
        "kelimeler": ["belediye", "baskan", "asfalt", "park", "bahce", "kaldirim", "altyapi", "su kesintisi", "temizlik", "cop", "imar", "ulasim", "otobus", "meydan", "sosyal yardim", "zabita"]
    },
    "RESMI_DUYURU": {
        "ad": "Resmi Duyuru ve İlan",
        "kelimeler": ["ihale", "ilan", "duyuru", "askiya", "teblig", "basvuru", "sonuc", "personel alimi", "mulakat", "kamu ilani", "yasaklama", "genel emir"]
    },
    "KULTUR_SANAT": {
        "ad": "Kültür, Sanat ve Turizm",
        "kelimeler": ["festival", "konser", "tiyatro", "sergi", "senlik", "etkinlik", "kultur", "sanat", "muze", "turizm", "odul", "gosteri", "anma", "kutlama", "yarismasi"]
    },
    "GUNCEL": {
        "ad": "Güncel ve Diğer",
        "kelimeler": []
    }
}

KURUM_TIPI_TANIMLARI = {
    "VALILIK": ("Valilik", "RESMI_DUYURU"),
    "KAYMAKAMLIK": ("Kaymakamlık", "RESMI_DUYURU"),
    "BELEDIYE": ("Belediye", "BELEDIYE_HIZMET"),
    "JANDARMA": ("İl Jandarma Komutanlığı", "ASAYIS_GUVENLIK"),
    "EMNIYET": ("İl Emniyet Müdürlüğü", "ASAYIS_GUVENLIK"),
    "MEB": ("İl/İlçe Milli Eğitim Müdürlüğü", "EGITIM"),
    "TARIM_ORMAN": ("İl/İlçe Tarım ve Orman Müdürlüğü", "TARIM_HAYVANCILIK"),
    "SAGLIK": ("İl Sağlık Müdürlüğü", "SAGLIK"),
    "AFAD": ("İl Afet ve Acil Durum Müdürlüğü", "AFET_ACIL"),
    "GENEL_KAMU": ("Resmi Kamu Kurumu", "GUNCEL")
}

def kategori_ve_kurum_belirle(baslik: str, icerik: str, kurum_tipi: str) -> tuple[str, str, str, str]:
    """
    Haber metnini ve kurum tipini analiz ederek en doğru kategori ve kurum etiketini belirler.
    Dönüş: (kategori_kodu, kategori_adi, nihai_kurum_tipi, kurum_tipi_adi)
    """
    metin = (baslik + " " + icerik).lower().translate(TURKCE_HARF_HARITASI)
    
    # 1. Asayiş ve Güvenlik Kontrolü (Valilik bültenlerinde Jandarma/Emniyet tespiti)
    if "jandarma" in metin and any(k in metin for k in ["operasyon", "uyusturucu", "kacak", "yakalandi", "tutukla", "asayis"]):
        return "ASAYIS_GUVENLIK", "Asayiş ve Güvenlik", "JANDARMA", "İl Jandarma Komutanlığı"
    
    if any(k in metin for k in ["emniyet mudurlugu", "polis", "narkotik", "terorle mucadele", "huzur uygulamasi", "trafik denetimi"]):
        return "ASAYIS_GUVENLIK", "Asayiş ve Güvenlik", "EMNIYET", "İl Emniyet Müdürlüğü"

    # 2. Kurum tipine göre varsayılan eşleme
    if kurum_tipi in KURUM_TIPI_TANIMLARI:
        varsayilan_ad, varsayilan_kat = KURUM_TIPI_TANIMLARI[kurum_tipi]
        # Eğer özel anahtar kelime eşleşmesi varsa onu al, yoksa varsayılan
        for kat_kodu, kat_bilgi in KATEGORI_TANIMLARI.items():
            if kat_kodu == "GUNCEL":
                continue
            if any(k in metin for k in kat_bilgi["kelimeler"]):
                return kat_kodu, kat_bilgi["ad"], kurum_tipi, varsayilan_ad
        
        kat_ad = KATEGORI_TANIMLARI.get(varsayilan_kat, {}).get("ad", "Güncel ve Diğer")
        return varsayilan_kat, kat_ad, kurum_tipi, varsayilan_ad

    # 3. Genel metin analizi
    for kat_kodu, kat_bilgi in KATEGORI_TANIMLARI.items():
        if kat_kodu == "GUNCEL":
            continue
        if any(k in metin for k in kat_bilgi["kelimeler"]):
            return kat_kodu, kat_bilgi["ad"], kurum_tipi, "Resmi Kamu Kurumu"

    return "GUNCEL", "Güncel ve Diğer", kurum_tipi, "Resmi Kamu Kurumu"

# ----------------------------------------------------------------------
# 3. MEDYA & METİN AYRIŞTIRMA (Gelişmiş Filtreleme & Kalite Motoru)
# ----------------------------------------------------------------------
ENGEL_GORSEL_KELIMELER = [
    "logo", "icon", "armasi", "arma", "bayrak", "avatar", "banner",
    "facebook", "twitter", "instagram", "youtube", "linkedin", "whatsapp",
    "footer", "header", ".svg", "reklam", "spacer", "pixel", "captcha"
]

def gorsel_kalitesini_artir(raw_url: str, base_url: str) -> str:
    """Küçük boyutlu önizlemeleri yüksek çözünürlüklü orijinal görsellere yükseltir."""
    if not raw_url:
        return ""
    
    tam_url = urljoin(base_url, raw_url.strip())
    low = tam_url.lower()

    if any(k in low for k in ENGEL_GORSEL_KELIMELER):
        return ""

    # /kucuk/ -> /buyuk/
    tam_url = re.sub(r"/(?:kucuk|thumb|thumbnail|min)/", "/buyuk/", tam_url, flags=re.IGNORECASE)
    
    # _thumb, _kucuk uzantılarını temizle
    tam_url = re.sub(r"[_-](?:thumb|thumbnail|kucuk|min|k)\.(jpg|jpeg|png|webp)", r".\1", tam_url, flags=re.IGNORECASE)

    # Query string'deki küçültme parametrelerini temizle
    parsed = urlparse(tam_url)
    if parsed.query:
        qs = parse_qs(parsed.query)
        filtrelenmis_qs = {k: v for k, v in qs.items() if k.lower() not in ["w", "h", "width", "height", "resize", "quality", "fit"]}
        yeni_query = "&".join(f"{k}={v[0]}" for k, v in filtrelenmis_qs.items())
        tam_url = parsed._replace(query=yeni_query).geturl()

    return tam_url

def video_ayikla(soup: BeautifulSoup, base_url: str) -> str:
    """HTML içinden video kaynaklarını (HTML5 video, YouTube, Vimeo, MP4) ayıklar."""
    # HTML5 Video
    for v in soup.find_all("video"):
        src = v.get("src")
        if src:
            return urljoin(base_url, src)
        for s in v.find_all("source"):
            s_src = s.get("src")
            if s_src:
                return urljoin(base_url, s_src)

    # iframe Video (YouTube, Vimeo)
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src") or iframe.get("data-src")
        if not src:
            continue
        low = src.lower()
        if "youtube.com" in low or "youtu.be" in low:
            if "embed/" in src:
                yt_id = src.split("embed/")[1].split("?")[0]
                return f"https://www.youtube.com/watch?v={yt_id}"
            return src
        if "vimeo.com" in low:
            return src

    # Doğrudan Video Linkleri
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        if href.endswith((".mp4", ".webm", ".mov", ".m4v")):
            return urljoin(base_url, a["href"])

    return None

def metin_temizle(ham_metin: str) -> str:
    """HTML etiketlerinden ve gereksiz boşluklardan arındırılmış temiz metin üretir."""
    if not ham_metin:
        return ""
    metin = html.unescape(ham_metin)
    metin = re.sub(r"\s+", " ", metin)
    return metin.strip()

# ----------------------------------------------------------------------
# 4. [ RSS Var mı? ] KARAR MOTORU (Auto-Discovery Engine)
# ----------------------------------------------------------------------
def rss_var_mi(hedef: dict, session: requests.Session) -> tuple[bool, str]:
    """Resmi kurum web sitesinde RSS beslemesi olup olmadığını otomatik tespit eder."""
    if hedef.get("has_rss") and hedef.get("rss_url"):
        return True, hedef["rss_url"]

    base = hedef["base_url"].rstrip("/")
    aday_yollar = [
        f"{base}/rss",
        f"{base}/rss.xml",
        f"{base}/feed",
        f"{base}/rss.php",
        f"{base}/haberler/rss",
        f"{base}/duyurular/rss"
    ]

    # 1. Ana sayfadaki <link rel="alternate"> etiketini ara
    try:
        resp = session.get(base, headers=DEFAULT_HEADERS, timeout=6, verify=False)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text[:100000], "html.parser")
            for link in soup.find_all("link", rel=lambda r: r and "alternate" in r):
                t = (link.get("type") or "").lower()
                href = link.get("href")
                if ("rss" in t or "xml" in t or "atom" in t) and href:
                    return True, urljoin(base, href)
    except Exception:
        pass

    # 2. Yaygın RSS yollarını kontrol et
    for aday in aday_yollar:
        try:
            head_resp = session.get(aday, headers=DEFAULT_HEADERS, timeout=5, verify=False, stream=True)
            content_type = (head_resp.headers.get("Content-Type") or "").lower()
            if head_resp.status_code == 200 and ("xml" in content_type or "rss" in content_type):
                return True, aday
        except Exception:
            continue

    return False, None

# ----------------------------------------------------------------------
# 5. [ RssService Engine ] (XML Parser & Media)
# ----------------------------------------------------------------------
def rss_servis_tara(hedef: dict, rss_url: str, limit: int = 4) -> list:
    """[RSS Var mı? -> Evet] RssService Engine: XML ayrıştırma ve zengin medya çıkarma."""
    haberler = []
    try:
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:limit]:
            link = entry.get("link", "").strip()
            baslik = metin_temizle(entry.get("title", ""))
            if not link or not baslik:
                continue

            ozet_html = entry.get("summary", "") or entry.get("description", "")
            content_list = entry.get("content", [])
            icerik_html = content_list[0].get("value", "") if (content_list and isinstance(content_list, list)) else ozet_html

            soup = BeautifulSoup(icerik_html, "html.parser")
            icerik_metin = metin_temizle(soup.get_text(separator=" "))
            if len(icerik_metin) < 15:
                icerik_metin = baslik

            # Medya Ayrıştırma: Görseller
            gorseller = []
            for enc in entry.get("enclosures", []):
                href = enc.get("href") or enc.get("url")
                if href and enc.get("type", "").startswith("image/"):
                    g = gorsel_kalitesini_artir(href, hedef["base_url"])
                    if g:
                        gorseller.append(g)

            for img in soup.find_all("img"):
                src = img.get("src") or img.get("data-src")
                if src:
                    g = gorsel_kalitesini_artir(src, hedef["base_url"])
                    if g:
                        gorseller.append(g)

            # Video Ayrıştırma
            video_url = None
            for enc in entry.get("enclosures", []):
                href = enc.get("href") or enc.get("url")
                if href and enc.get("type", "").startswith("video/"):
                    video_url = href
                    break
            if not video_url:
                video_url = video_ayikla(soup, hedef["base_url"])

            yayin_tarihi = entry.get("published", "") or entry.get("updated", "")
            temiz_gorseller = list(dict.fromkeys(gorseller))[:10]
            kapak_gorseli = temiz_gorseller[0] if temiz_gorseller else None
            haber_id = id_uret(link)

            # Kategori ve Kurum Analizi
            kat_kod, kat_ad, nihai_kt, kt_ad = kategori_ve_kurum_belirle(baslik, icerik_metin, hedef["kurum_tipi"])

            haberler.append({
                "id": haber_id,
                "baslik": baslik,
                "ozet": icerik_metin[:240] + ("..." if len(icerik_metin) > 240 else ""),
                "icerik": icerik_metin[:5000],
                "ilKodu": hedef["plaka"],
                "ilAdi": hedef["il_adi"],
                "ilceAdi": hedef["ilce_adi"],
                "kurumId": hedef["kurum_id"],
                "kurumAdi": hedef["kurum_adi"],
                "kurumTipi": nihai_kt,
                "kurumTipiAdi": kt_ad,
                "kaynakMotor": "RSS",
                "gorselUrls": temiz_gorseller,
                "kapakGorseli": kapak_gorseli,
                "videoUrl": video_url,
                "kaynakUrl": link,
                "yayinTarihiMetin": yayin_tarihi,
                "kategori": kat_kod,
                "kategoriAdi": kat_ad,
                "etiketler": [hedef["il_adi"], hedef["ilce_adi"], kt_ad, kat_ad],
                "aktifMi": True,
                "onayDurumu": "YAYINDA",
                "okunmaSayisi": 0,
                "begeniSayisi": 0
            })
    except Exception as e:
        print(f"[RSS MOTOR HATA] {hedef['kurum_adi']}: {e}")
    return haberler

# ----------------------------------------------------------------------
# 6. [ Dynamic HTML Scraper ] (JSoup / Headless Worker / BS4)
# ----------------------------------------------------------------------
def html_scraper_tara(hedef: dict, seciciler: dict, session: requests.Session, limit: int = 3) -> list:
    """[RSS Var mı? -> Hayır] Dynamic HTML Scraper: Detay tarama, medya ve içerik çıkarma."""
    haberler = []
    target_url = hedef.get("target_url") or f"{hedef['base_url'].rstrip('/')}/haberler"
    
    try:
        resp = session.get(target_url, headers=DEFAULT_HEADERS, timeout=12, verify=False)
        if resp.status_code != 200:
            resp = session.get(hedef["base_url"], headers=DEFAULT_HEADERS, timeout=12, verify=False)
            if resp.status_code != 200:
                return haberler

        soup = BeautifulSoup(resp.text, "html.parser")
        link_etiketleri = soup.select(seciciler.get("list_container", "a"))

        detay_linkleri = []
        for a in link_etiketleri:
            href = a.get("href")
            if not href or href.startswith("javascript") or href == "#":
                continue
            tam_url = urljoin(hedef["base_url"], href)
            
            if tam_url.startswith("http") and tam_url not in detay_linkleri:
                detay_linkleri.append(tam_url)
            if len(detay_linkleri) >= limit:
                break

        for detay_url in detay_linkleri:
            try:
                d_resp = session.get(detay_url, headers=DEFAULT_HEADERS, timeout=12, verify=False)
                if d_resp.status_code != 200:
                    continue
                d_soup = BeautifulSoup(d_resp.text, "html.parser")

                # Başlık
                baslik_el = d_soup.select_one(seciciler.get("title", "h1"))
                baslik = baslik_el.get_text(strip=True) if baslik_el else (d_soup.title.get_text(strip=True) if d_soup.title else "")
                baslik = metin_temizle(baslik)
                if not baslik:
                    continue

                # İçerik
                icerik_el = d_soup.select_one(seciciler.get("content", "article"))
                icerik = icerik_el.get_text(separator=" ", strip=True) if icerik_el else ""
                if len(icerik) < 30:
                    paragraflar = [p.get_text(strip=True) for p in d_soup.find_all("p") if len(p.get_text(strip=True)) > 25]
                    icerik = " ".join(paragraflar)
                icerik = metin_temizle(icerik)
                if len(icerik) < 20:
                    continue

                # Görseller
                gorseller = []
                for el in d_soup.select(seciciler.get("images", "img")):
                    raw_src = el.get("href") if el.name == "a" else (el.get("data-src") or el.get("src"))
                    if raw_src:
                        g = gorsel_kalitesini_artir(raw_src, hedef["base_url"])
                        if g:
                            gorseller.append(g)

                # Video
                video_url = None
                if seciciler.get("video"):
                    v_el = d_soup.select_one(seciciler["video"])
                    if v_el:
                        v_src = v_el.get("src") or v_el.get("href")
                        if v_src:
                            video_url = urljoin(hedef["base_url"], v_src)
                if not video_url:
                    video_url = video_ayikla(d_soup, hedef["base_url"])

                # Tarih
                tarih_metin = ""
                if seciciler.get("date"):
                    t_el = d_soup.select_one(seciciler["date"])
                    if t_el:
                        tarih_metin = metin_temizle(t_el.get_text(strip=True))

                temiz_gorseller = list(dict.fromkeys(gorseller))[:10]
                kapak_gorseli = temiz_gorseller[0] if temiz_gorseller else None
                haber_id = id_uret(detay_url)

                # Kategori ve Kurum Analizi
                kat_kod, kat_ad, nihai_kt, kt_ad = kategori_ve_kurum_belirle(baslik, icerik, hedef["kurum_tipi"])

                haberler.append({
                    "id": haber_id,
                    "baslik": baslik,
                    "ozet": icerik[:240] + ("..." if len(icerik) > 240 else ""),
                    "icerik": icerik[:5000],
                    "ilKodu": hedef["plaka"],
                    "ilAdi": hedef["il_adi"],
                    "ilceAdi": hedef["ilce_adi"],
                    "kurumId": hedef["kurum_id"],
                    "kurumAdi": hedef["kurum_adi"],
                    "kurumTipi": nihai_kt,
                    "kurumTipiAdi": kt_ad,
                    "kaynakMotor": "SCRAPER",
                    "gorselUrls": temiz_gorseller,
                    "kapakGorseli": kapak_gorseli,
                    "videoUrl": video_url,
                    "kaynakUrl": detay_url,
                    "yayinTarihiMetin": tarih_metin,
                    "kategori": kat_kod,
                    "kategoriAdi": kat_ad,
                    "etiketler": [hedef["il_adi"], hedef["ilce_adi"], kt_ad, kat_ad],
                    "aktifMi": True,
                    "onayDurumu": "YAYINDA",
                    "okunmaSayisi": 0,
                    "begeniSayisi": 0
                })
            except Exception:
                continue
    except Exception as e:
        print(f"[HTML SCRAPER HATA] {hedef['kurum_adi']}: {e}")
    return haberler

# ----------------------------------------------------------------------
# 7. OTONOM DÖNGÜ & AKIŞ ORKESTRASYONU
# ----------------------------------------------------------------------
def kurum_tara_is(hedef: dict, varsayilan_seciciler: dict, limit: int = 3) -> list:
    """Tek bir resmi kurum için rapor akış mimarisini işletir."""
    with requests.Session() as session:
        has_rss, rss_url = rss_var_mi(hedef, session)
        if has_rss and rss_url:
            haberler = rss_servis_tara(hedef, rss_url, limit=limit)
        else:
            seciciler = hedef.get("seciciler") or varsayilan_seciciler
            haberler = html_scraper_tara(hedef, seciciler, session, limit=limit)
    return haberler

# ----------------------------------------------------------------------
# 8. HEDEFLERİ HAZIRLAMA (81 İl Valiliği, MEB, Tarım, Sağlık, AFAD, Emniyet/Jandarma)
# ----------------------------------------------------------------------
def hedefleri_yukle(args) -> tuple[list, dict]:
    """Tüm resmi kurumları yapılandırır ve tarama havuzuna dahil eder."""
    with open("kurum_listesi.json", "r", encoding="utf-8") as f:
        config = json.load(f)

    templates = config.get("selector_templates", {})
    varsayilan_isay = templates.get("ISAY_GOV_TR", {})
    meb_sablon = templates.get("MEB_GOV_TR", varsayilan_isay)
    tarim_sablon = templates.get("TARIM_ORMAN_GOV_TR", varsayilan_isay)
    saglik_sablon = templates.get("SAGLIK_GOV_TR", varsayilan_isay)
    afad_sablon = templates.get("AFAD_GOV_TR", varsayilan_isay)
    egm_sablon = templates.get("EGM_JANDARMA", varsayilan_isay)

    with open("turkiye_il_ilce.json", "r", encoding="utf-8") as f:
        il_ilce_haritasi = json.load(f)

    hedef_listesi = []

    # Plaka filtreleme kuralları
    secili_plakalar = set()
    if args.plaka:
        secili_plakalar.add(int(args.plaka))
    elif args.plaka_aralik:
        bas, bit = map(int, args.plaka_aralik.split("-"))
        secili_plakalar = set(range(bas, bit + 1))
    elif args.rotasyon:
        import datetime
        saat = datetime.datetime.now().hour
        rotasyon_grubu = (saat % 8) * 10 + 1
        secili_plakalar = set(range(rotasyon_grubu, min(rotasyon_grubu + 10, 82)))
    elif args.hepsi:
        secili_plakalar = set(range(1, 82))
    else:
        # Varsayılan başlangıç illeri
        secili_plakalar = {1, 2, 6, 34, 35}

    istenen_kt = (args.kurum_tipi or "hepsi").upper()

    # 1. 81 İL İÇİN TÜM KAMU KURUMLARINI OLUŞTUR
    for plaka_str, il_bilgi in il_ilce_haritasi.items():
        plaka = int(plaka_str)
        if plaka not in secili_plakalar:
            continue

        il_adi = il_bilgi["il"]
        slug = il_bilgi["slug"]

        # A) VALİLİK
        if istenen_kt in ["HEPSI", "VALILIK"]:
            k_id = f"{plaka:02d}_merkez_valilik"
            hedef_listesi.append({
                "plaka": plaka, "il_adi": il_adi, "ilce_adi": "Merkez",
                "kurum_id": k_id, "kurum_adi": f"{il_adi} Valiliği",
                "kurum_tipi": "VALILIK",
                "base_url": f"http://www.{slug}.gov.tr",
                "target_url": f"http://www.{slug}.gov.tr/haberler",
                "has_rss": False, "rss_url": None, "seciciler": varsayilan_isay
            })

        # B) İL MİLLİ EĞİTİM MÜDÜRLÜĞÜ (MEB)
        if istenen_kt in ["HEPSI", "MEB", "EGITIM"]:
            k_meb_id = f"{plaka:02d}_merkez_meb"
            hedef_listesi.append({
                "plaka": plaka, "il_adi": il_adi, "ilce_adi": "Merkez",
                "kurum_id": k_meb_id, "kurum_adi": f"{il_adi} İl Milli Eğitim Müdürlüğü",
                "kurum_tipi": "MEB",
                "base_url": f"https://{slug}.meb.gov.tr",
                "target_url": f"https://{slug}.meb.gov.tr",
                "has_rss": False, "rss_url": None, "seciciler": meb_sablon
            })

        # C) İL TARIM VE ORMAN MÜDÜRLÜĞÜ
        if istenen_kt in ["HEPSI", "TARIM_ORMAN", "TARIM"]:
            k_tarim_id = f"{plaka:02d}_merkez_tarim"
            hedef_listesi.append({
                "plaka": plaka, "il_adi": il_adi, "ilce_adi": "Merkez",
                "kurum_id": k_tarim_id, "kurum_adi": f"{il_adi} İl Tarım ve Orman Müdürlüğü",
                "kurum_tipi": "TARIM_ORMAN",
                "base_url": f"https://{slug}.tarimorman.gov.tr",
                "target_url": f"https://{slug}.tarimorman.gov.tr",
                "has_rss": False, "rss_url": None, "seciciler": tarim_sablon
            })

        # D) İL SAĞLIK MÜDÜRLÜĞÜ
        if istenen_kt in ["HEPSI", "SAGLIK"]:
            k_saglik_id = f"{plaka:02d}_merkez_saglik"
            hedef_listesi.append({
                "plaka": plaka, "il_adi": il_adi, "ilce_adi": "Merkez",
                "kurum_id": k_saglik_id, "kurum_adi": f"{il_adi} İl Sağlık Müdürlüğü",
                "kurum_tipi": "SAGLIK",
                "base_url": f"https://{slug}ism.saglik.gov.tr",
                "target_url": f"https://{slug}ism.saglik.gov.tr",
                "has_rss": False, "rss_url": None, "seciciler": saglik_sablon
            })

        # E) İL AFAD MÜDÜRLÜĞÜ
        if istenen_kt in ["HEPSI", "AFAD"]:
            k_afad_id = f"{plaka:02d}_merkez_afad"
            hedef_listesi.append({
                "plaka": plaka, "il_adi": il_adi, "ilce_adi": "Merkez",
                "kurum_id": k_afad_id, "kurum_adi": f"{il_adi} İl Afet ve Acil Durum Müdürlüğü",
                "kurum_tipi": "AFAD",
                "base_url": f"https://{slug}.afad.gov.tr",
                "target_url": f"https://{slug}.afad.gov.tr",
                "has_rss": False, "rss_url": None, "seciciler": afad_sablon
            })

        # F) İLÇELER (Kaymakamlıklar & İlçe MEB)
        for ilce in il_bilgi.get("ilceler", []):
            ilce_slug = turkce_slug(ilce)
            if not ilce_slug or ilce_slug == "merkez":
                continue
            if args.ilce and turkce_slug(args.ilce) != ilce_slug:
                continue

            # İlçe Kaymakamlığı
            if istenen_kt in ["HEPSI", "KAYMAKAMLIK"]:
                k_ilce_id = f"{plaka:02d}_{ilce_slug}_kaymakamlik"
                hedef_listesi.append({
                    "plaka": plaka, "il_adi": il_adi, "ilce_adi": ilce,
                    "kurum_id": k_ilce_id, "kurum_adi": f"{ilce} Kaymakamlığı",
                    "kurum_tipi": "KAYMAKAMLIK",
                    "base_url": f"http://www.{ilce_slug}.gov.tr",
                    "target_url": f"http://www.{ilce_slug}.gov.tr/haberler",
                    "has_rss": False, "rss_url": None, "seciciler": varsayilan_isay
                })

            # İlçe MEB
            if istenen_kt in ["HEPSI", "MEB", "EGITIM"]:
                k_ilce_meb_id = f"{plaka:02d}_{ilce_slug}_meb"
                hedef_listesi.append({
                    "plaka": plaka, "il_adi": il_adi, "ilce_adi": ilce,
                    "kurum_id": k_ilce_meb_id, "kurum_adi": f"{ilce} İlçe Milli Eğitim Müdürlüğü",
                    "kurum_tipi": "MEB",
                    "base_url": f"https://{ilce_slug}.meb.gov.tr",
                    "target_url": f"https://{ilce_slug}.meb.gov.tr",
                    "has_rss": False, "rss_url": None, "seciciler": meb_sablon
                })

    # 2. MERKEZİ GÜVENLİK KURUMLARI (Emniyet & Jandarma Genel Akışı)
    if istenen_kt in ["HEPSI", "EMNIYET", "JANDARMA", "ASAYIS"]:
        hedef_listesi.append({
            "plaka": 6, "il_adi": "Ankara", "ilce_adi": "Merkez",
            "kurum_id": "06_jandarma_genel", "kurum_adi": "Jandarma Genel Komutanlığı",
            "kurum_tipi": "JANDARMA",
            "base_url": "https://www.jandarma.gov.tr",
            "target_url": "https://www.jandarma.gov.tr/haberler",
            "has_rss": False, "rss_url": None, "seciciler": egm_sablon
        })
        hedef_listesi.append({
            "plaka": 6, "il_adi": "Ankara", "ilce_adi": "Merkez",
            "kurum_id": "06_egm_genel", "kurum_adi": "Emniyet Genel Müdürlüğü",
            "kurum_tipi": "EMNIYET",
            "base_url": "https://www.egm.gov.tr",
            "target_url": "https://www.egm.gov.tr/haberler",
            "has_rss": False, "rss_url": None, "seciciler": egm_sablon
        })

    # 3. ÖZEL VE LİSTELENMİŞ KURUMLAR (kurum_listesi.json)
    for ozel in config.get("ozel_kurumlar", []):
        plaka = ozel["plaka"]
        if plaka in secili_plakalar:
            t_id = ozel.get("template_id", "ISAY_GOV_TR")
            seciciler = templates.get(t_id, varsayilan_isay)
            hedef_listesi.append({
                "plaka": plaka, "il_adi": ozel["il_adi"], "ilce_adi": ozel["ilce_adi"],
                "kurum_id": ozel["kurum_id"], "kurum_adi": ozel["kurum_adi"],
                "kurum_tipi": ozel["kurum_tipi"],
                "base_url": ozel["base_url"], "target_url": ozel["target_url"],
                "has_rss": ozel.get("has_rss", False), "rss_url": ozel.get("rss_url"),
                "seciciler": seciciler
            })

    # Duplicate kurum_id'leri temizle
    benzersiz_hedefler = {}
    for h in hedef_listesi:
        benzersiz_hedefler[h["kurum_id"]] = h

    return list(benzersiz_hedefler.values()), varsayilan_isay

# ----------------------------------------------------------------------
# 9. FIREBASE BAĞLANTISI, YAZIM VE OTOMATİK TEMİZLİK (2 GÜNLÜK TTL)
# ----------------------------------------------------------------------
def eski_haberleri_temizle(db_client, omur_gun: int = 2):
    """
    Sistemi yormamak ve veritabanını güncel tutmak için
    2 günü (48 saati) dolduran eski haberleri Firestore'dan otomatik siler.
    """
    if db_client is None:
        print("[TEMİZLİK] Dry-run modu: Yerel testte silme işlemi atlandı.")
        return

    import datetime
    from firebase_admin import firestore

    col_ref = db_client.collection(KOLEKSIYON_ADI)
    su_an = datetime.datetime.now(datetime.timezone.utc)
    esik_tarih = su_an - datetime.timedelta(days=omur_gun)

    try:
        # 1. Öncelik: silinmeTarihi alanı geçmiş olanlar
        eski_docs = list(col_ref.where("silinmeTarihi", "<=", su_an).limit(400).stream())
        
        # 2. Alternatif: silinmeTarihi olmayan eski kayıtlar için olusturulmaTarihi kontrolü
        if not eski_docs:
            eski_docs = list(col_ref.where("olusturulmaTarihi", "<=", esik_tarih).limit(400).stream())

        if not eski_docs:
            print("[TEMİZLİK] 2 günden eski temizlenecek haber bulunamadı. Sistem güncel.")
            return

        silinen_sayisi = 0
        batch = db_client.batch()
        for doc in eski_docs:
            batch.delete(doc.reference)
            silinen_sayisi += 1

        batch.commit()
        print(f"🧹 [OTOMATİK TEMİZLİK] 2 günü aşan toplam {silinen_sayisi} eski haber Firestore'dan temizlendi.")

    except Exception as e:
        print(f"[TEMİZLİK UYARI] Eski haberler temizlenirken hata oluştu: {e}")

def firebase_baglan(dry_run: bool):
    """Firebase Firestore istemcisini başlatır."""
    if dry_run:
        print("[FIREBASE] Dry-run modu aktif. Veriler Firebase yerine yerel JSON dosyasına yazılacak.")
        return None

    firebase_json_str = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
    cred = None

    if firebase_json_str:
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore
            cred_dict = json.loads(firebase_json_str)
            cred = credentials.Certificate(cred_dict)
        except Exception as e:
            print(f"[FIREBASE UYARI] FIREBASE_SERVICE_ACCOUNT çözümlenemedi: {e}")

    elif os.path.exists("serviceAccountKey.json"):
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore
            cred = credentials.Certificate("serviceAccountKey.json")
        except Exception as e:
            print(f"[FIREBASE UYARI] serviceAccountKey.json yüklenemedi: {e}")

    if cred:
        import firebase_admin
        from firebase_admin import firestore
        if not firebase_admin._apps:
            firebase_admin.initialize_app(cred)
        print("[FIREBASE] Firestore bağlantısı başarıyla kuruldu.")
        return firestore.client()

    print("[FIREBASE UYARI] Firebase kimlik bilgisi bulunamadı! Otomatik Dry-Run moduna geçiliyor.")
    return None

def haberleri_kaydet(haberler: list, db_client, omur_gun: int = 2):
    """Toplanan haberleri 2 günlük otomatik silinme (TTL) alanlarıyla Firestore'a yazar."""
    if not haberler:
        print("[KAYIT] Kaydedilecek haber bulunamadı.")
        return

    import datetime
    su_an = datetime.datetime.now(datetime.timezone.utc)
    silinme_zamani = su_an + datetime.timedelta(days=omur_gun)

    if db_client is None:
        test_dosyasi = "saha_haberleri_test.json"
        zengin_haberler = []
        for h in haberler:
            hz = dict(h)
            hz["olusturulmaZamaniIso"] = su_an.isoformat()
            hz["silinmeZamaniIso"] = silinme_zamani.isoformat()
            hz["gecerlilikSuresiGun"] = omur_gun
            zengin_haberler.append(hz)

        with open(test_dosyasi, "w", encoding="utf-8") as f:
            json.dump(zengin_haberler, f, ensure_ascii=False, indent=2)
        print(f"[YEREL KAYIT] Toplam {len(haberler)} kategorili haber (2 gün ömürlü) '{test_dosyasi}' dosyasına kaydedildi.")
        
        istatistik = {}
        for h in haberler:
            k = h.get("kategoriAdi", "Diğer")
            istatistik[k] = istatistik.get(k, 0) + 1
        print("\n📊 Kategori Dağılımı:")
        for k, v in istatistik.items():
            print(f"  • {k}: {v} haber")
        return

    import firebase_admin
    from firebase_admin import firestore
    col_ref = db_client.collection(KOLEKSIYON_ADI)
    
    toplam = len(haberler)
    batch_boyutu = 350
    for i in range(0, toplam, batch_boyutu):
        batch = db_client.batch()
        grup = haberler[i:i + batch_boyutu]
        for h in grup:
            doc_ref = col_ref.document(h["id"])
            h_firestore = dict(h)
            # 2 Günlük TTL ve Zaman Etiketleri
            h_firestore["olusturulmaTarihi"] = firestore.SERVER_TIMESTAMP
            h_firestore["olusturulmaZamaniIso"] = su_an.isoformat()
            h_firestore["silinmeTarihi"] = silinme_zamani
            h_firestore["gecerlilikSuresiGun"] = omur_gun
            batch.set(doc_ref, h_firestore, merge=True)
        batch.commit()
        print(f"[FIREBASE BATCH] {min(i + batch_boyutu, toplam)} / {toplam} haber kaydedildi.")

    print(f"[BAŞARILI] Toplam {toplam} haber Firestore '{KOLEKSIYON_ADI}' koleksiyonuna işlendi. (2 Günlük TTL aktif)")


# ----------------------------------------------------------------------
# 10. ANA ÇALIŞTIRICI (MAIN)
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Novra Saha Botu - 81 İl ve Resmi Kurumlar (Jandarma, Emniyet, MEB, Tarım vb.)")
    parser.add_argument("--plaka", type=int, help="Sadece belirtilen il plakasını tara (örn: 2)")
    parser.add_argument("--plaka-aralik", type=str, help="Plaka aralığını tara (örn: 1-10)")
    parser.add_argument("--ilce", type=str, help="Belirli bir ilçeyi tara (örn: kahta)")
    parser.add_argument("--kurum-tipi", type=str, default="hepsi", help="Kurum tipi filtresi (meb, tarim, saglik, afad, jandarma, emniyet, valilik, kaymakamlik, hepsi)")
    parser.add_argument("--rotasyon", action="store_true", help="Günün saatine göre rotasyonel il grubu tara")
    parser.add_argument("--hepsi", action="store_true", help="Tüm 81 il ve ilçeleri tara")
    parser.add_argument("--dry-run", action="store_true", help="Firebase yerine yerel JSON çıktısı al")
    parser.add_argument("--limit", type=int, default=3, help="Kurum başına çekilecek haber sayısı (varsayılan: 3)")
    parser.add_argument("--workers", type=int, default=16, help="Paralel worker sayısı (varsayılan: 16)")
    parser.add_argument("--omur-gun", type=int, default=2, help="Haberlerin veritabanında kalma süresi (gün) - varsayılan: 2")
    parser.add_argument("--sadece-temizle", action="store_true", help="Tarama yapmadan sadece süresi dolan eski haberleri temizler")
    args = parser.parse_args()

    print("=" * 75)
    print("NOVRA SAHA BOTU v1.4.1 BAŞLATILDI")
    print("Mimar: Muhammed Yasin KORKUT ve Beyza KARAKAŞ | Koleksiyon: saha_haberleri")
    print(f"Filtreler -> Plaka: {args.plaka or 'Hepsi'}, Kurum Tipi: {args.kurum_tipi.upper()}, Haber Ömrü: {args.omur_gun} Gün")
    print("=" * 75)

    db_client = firebase_baglan(args.dry_run)

    # 1. OTOMATİK ESKİ HABER TEMİZLİĞİ (2 Günü Dolduranları Temizle)
    eski_haberleri_temizle(db_client, args.omur_gun)

    if args.sadece_temizle:
        print("[BİTTİ] Sadece temizlik modu tamamlandı.")
        return

    # 2. HEDEFLERİ YÜKLE VE TARA
    hedefler, varsayilan_seciciler = hedefleri_yukle(args)
    print(f"[HEDEF] Toplam {len(hedefler)} resmi kurum tarama havuzuna alındı.")

    toplanan_haberler = []
    print(f"[TARAMA] {args.workers} paralel worker ile kamu kurumları taranıyor...")

    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        gelecek_isler = {
            executor.submit(kurum_tara_is, h, varsayilan_seciciler, args.limit): h
            for h in hedefler
        }
        for future in as_completed(gelecek_isler):
            hedef = gelecek_isler[future]
            try:
                sonuclar = future.result()
                if sonuclar:
                    toplanan_haberler.extend(sonuclar)
                    ornek = sonuclar[0]
                    print(f" -> [+] {hedef['kurum_adi']} [{ornek['kategoriAdi']}]: {len(sonuclar)} haber çekildi.")
            except Exception as e:
                print(f" -> [-] {hedef['kurum_adi']} hata: {e}")

    print("-" * 75)
    print(f"[TAMAMLANDI] Toplam {len(toplanan_haberler)} resmi haber ve duyuru kategorilendirildi.")

    # 3. HABERLERİ 2 GÜNLÜK TTL İLE FIREBASE'E YAZ
    haberleri_kaydet(toplanan_haberler, db_client, args.omur_gun)

if __name__ == "__main__":
    main()

