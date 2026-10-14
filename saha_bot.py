"""
================================================================================
NOVRA A.İ. - Versiyon 1.4 Kapsamlı Proje
2. YENİ BOT: NOVRA SAHA (NOVRA FIELD BOT)
Hazırlayan: Muhammed Yasin KORKUT
Tarih: 14.10.2026

AKIŞ MİMARİSİ:
[ Resmi Kurum Web Siteleri ] (81 İl Valiliği & 922 İlçe Kaymakamlık/Belediyesi)
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
      [ İl / İlçe Etiketleme ]
      (plaka, ilAdi, ilceAdi, kurumId, kurumTipi, kategori)
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
# 1. TEMEL YAPILANDIRMA & YARDIMCI FONKSİYONLAR
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
# 2. MEDYA & METİN AYRIŞTIRMA (Gelişmiş Filtreleme & Kalite Motoru)
# ----------------------------------------------------------------------
ENGEL_GORSEL_KELIMELER = [
    "logo", "icon", "armasi", "arma", "bayrak", "avatar", "banner",
    "facebook", "twitter", "instagram", "youtube", "linkedin", "whatsapp",
    "footer", "header", ".svg", "reklam", "spacer", "pixel", "captcha"
]

def gorsel_kalitesini_artir(raw_url: str, base_url: str) -> str:
    """
    Düşük çözünürlüklü veya kırpılmış küçük resimleri yüksek çözünürlüklü
    orijinal hallerine dönüştürür.
    """
    if not raw_url:
        return ""
    
    # Tam URL'ye dönüştür
    tam_url = urljoin(base_url, raw_url.strip())
    low = tam_url.lower()

    # İstenmeyen statik görsel ve logoları ele
    if any(k in low for k in ENGEL_GORSEL_KELIMELER):
        return ""

    # Yüksek çözünürlük optimizasyonları
    # /kucuk/ -> /buyuk/
    tam_url = re.sub(r"/(?:kucuk|thumb|thumbnail|min)/", "/buyuk/", tam_url, flags=re.IGNORECASE)
    
    # _thumb, _kucuk son eklerini temizle (örn: haber_thumb.jpg -> haber.jpg)
    tam_url = re.sub(r"[_-](?:thumb|thumbnail|kucuk|min|k)\.(jpg|jpeg|png|webp)", r".\1", tam_url, flags=re.IGNORECASE)

    # Query string'deki w=, h=, resize= parametrelerini temizleyerek tam çözünürlüğü elde et
    parsed = urlparse(tam_url)
    if parsed.query:
        qs = parse_qs(parsed.query)
        filtrelenmis_qs = {k: v for k, v in qs.items() if k.lower() not in ["w", "h", "width", "height", "resize", "quality", "fit"]}
        yeni_query = "&".join(f"{k}={v[0]}" for k, v in filtrelenmis_qs.items())
        tam_url = parsed._replace(query=yeni_query).geturl()

    return tam_url

def video_ayikla(soup: BeautifulSoup, base_url: str) -> str:
    """
    HTML içinden video kaynaklarını (HTML5 video, YouTube, Vimeo vb.) ayıklar.
    """
    # 1. HTML5 Video etiketleri
    for v in soup.find_all("video"):
        src = v.get("src")
        if src:
            return urljoin(base_url, src)
        for s in v.find_all("source"):
            s_src = s.get("src")
            if s_src:
                return urljoin(base_url, s_src)

    # 2. iframe Video Oynatıcıları (YouTube, Vimeo vb.)
    for iframe in soup.find_all("iframe"):
        src = iframe.get("src") or iframe.get("data-src")
        if not src:
            continue
        low = src.lower()
        if "youtube.com" in low or "youtu.be" in low:
            # YouTube embed'i standart watch formatına veya temiz embed formatına çevir
            if "embed/" in src:
                yt_id = src.split("embed/")[1].split("?")[0]
                return f"https://www.youtube.com/watch?v={yt_id}"
            return src
        if "vimeo.com" in low:
            return src

    # 3. Doğrudan video linkleri
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        if href.endswith((".mp4", ".webm", ".mov", ".m4v")):
            return urljoin(base_url, a["href"])

    return None

def metin_temizle(ham_metin: str) -> str:
    """HTML ve fazla boşluklardan arındırılmış temiz metin üretir."""
    if not ham_metin:
        return ""
    metin = html.unescape(ham_metin)
    metin = re.sub(r"\s+", " ", metin)
    return metin.strip()

def kategori_tahmin_et(baslik: str, icerik: str) -> str:
    """Haber metninden otomatik kategori sınıflandırması yapar."""
    metin = (baslik + " " + icerik).lower()
    if any(w in metin for w in ["asayis", "polis", "jandarma", "operasyon", "hapis", "tutukla", "uyusturucu", "kacak", "trafik"]):
        return "ASAYIS"
    if any(w in metin for w in ["okul", "ogrenci", "ogretmen", "meb", "sinav", "burs", "universite", "egitim", "kutuphane"]):
        return "EGITIM"
    if any(w in metin for w in ["hastane", "saglik", "doktor", "asi", "hemsire", "randevu", "tibbi", "tedavi"]):
        return "SAGLIK"
    if any(w in metin for w in ["ihale", "ilan", "duyuru", "askiya", "teblig", "basvuru", "sonuc"]):
        return "DUYURU"
    if any(w in metin for w in ["festival", "konser", "tiyatro", "sergi", "senlik", "etkinlik", "kultur", "sanat", "muze"]):
        return "KULTUR_SANAT"
    if any(w in metin for w in ["tarim", "ciftci", "hasat", "sulama", "tohum", "hayvancilik", "orman"]):
        return "TARIM"
    return "GUNCEL"

# ----------------------------------------------------------------------
# 3. [ RSS Var mı? ] KARAR MOTORU (Auto-Discovery Engine)
# ----------------------------------------------------------------------
def rss_var_mi(hedef: dict, session: requests.Session) -> tuple[bool, str]:
    """
    Resmi kurum web sitesinde RSS feed olup olmadığını tespit eder.
    Varsa (True, rss_url), yoksa (False, None) döner.
    """
    # Önceden hedefe manuel/listeden tanımlanmışsa
    if hedef.get("has_rss") and hedef.get("rss_url"):
        return True, hedef["rss_url"]

    base = hedef["base_url"].rstrip("/")
    aday_yollar = [
        f"{base}/rss",
        f"{base}/rss.xml",
        f"{base}/feed",
        f"{base}/haberler/rss",
        f"{base}/duyurular/rss"
    ]

    # 1. Adım: Ana sayfanın <link rel="alternate"> etiketlerini kontrol et
    try:
        resp = session.get(base, headers=DEFAULT_HEADERS, timeout=6, verify=False)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text[:100000], "html.parser")
            for link in soup.find_all("link", rel=lambda r: r and "alternate" in r):
                t = (link.get("type") or "").lower()
                href = link.get("href")
                if ("rss" in t or "xml" in t or "atom" in t) and href:
                    rss_url = urljoin(base, href)
                    return True, rss_url
    except Exception:
        pass

    # 2. Adım: Yaygın RSS uç noktalarını hızlıca dene (HEAD/GET)
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
# 4. [ RssService Engine ] (XML Parser & Media)
# ----------------------------------------------------------------------
def rss_servis_tara(hedef: dict, rss_url: str, limit: int = 4) -> list:
    """
    [RSS Var mı? -> Evet]
    feedparser ile XML'i ayrıştırır, yüksek çözünürlüklü görselleri,
    varsa video URL'sini ve metin içeriğini çıkarır.
    """
    haberler = []
    try:
        feed = feedparser.parse(rss_url)
        for entry in feed.entries[:limit]:
            link = entry.get("link", "").strip()
            baslik = metin_temizle(entry.get("title", ""))
            if not link or not baslik:
                continue

            # Özet ve İçerik
            ozet_html = entry.get("summary", "") or entry.get("description", "")
            content_list = entry.get("content", [])
            if content_list and isinstance(content_list, list):
                icerik_html = content_list[0].get("value", "")
            else:
                icerik_html = ozet_html

            soup = BeautifulSoup(icerik_html, "html.parser")
            icerik_metin = metin_temizle(soup.get_text(separator=" "))
            if len(icerik_metin) < 15:
                icerik_metin = baslik

            # Medya Ayrıştırma: Görseller
            gorseller = []
            
            # Enclosure'dan gelen görseller
            for enc in entry.get("enclosures", []):
                href = enc.get("href") or enc.get("url")
                if href and enc.get("type", "").startswith("image/"):
                    g = gorsel_kalitesini_artir(href, hedef["base_url"])
                    if g:
                        gorseller.append(g)

            # HTML içindeki img etiketleri
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

            # Tarih
            yayin_tarihi = entry.get("published", "") or entry.get("updated", "")

            # Kapak görseli
            temiz_gorseller = list(dict.fromkeys(gorseller))[:10]
            kapak_gorseli = temiz_gorseller[0] if temiz_gorseller else None

            haber_id = id_uret(link)
            kategori = kategori_tahmin_et(baslik, icerik_metin)

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
                "kurumTipi": hedef["kurum_tipi"],
                "kaynakMotor": "RSS",
                "gorselUrls": temiz_gorseller,
                "kapakGorseli": kapak_gorseli,
                "videoUrl": video_url,
                "kaynakUrl": link,
                "yayinTarihiMetin": yayin_tarihi,
                "kategori": kategori,
                "etiketler": [hedef["il_adi"], hedef["ilce_adi"], hedef["kurum_adi"], kategori],
                "aktifMi": True,
                "onayDurumu": "YAYINDA",
                "okunmaSayisi": 0,
                "begeniSayisi": 0
            })
    except Exception as e:
        print(f"[RSS MOTOR HATA] {hedef['kurum_adi']}: {e}")
    return haberler

# ----------------------------------------------------------------------
# 5. [ Dynamic HTML Scraper ] (JSoup / Headless Worker / BS4)
# ----------------------------------------------------------------------
def html_scraper_tara(hedef: dict, seciciler: dict, session: requests.Session, limit: int = 3) -> list:
    """
    [RSS Var mı? -> Hayır]
    Hedef kurumun haberler sayfasını tarar, detay sayfalarına girer,
    medya (yüksek çözünürlüklü görsel & video) ve metin ayrıştırması yapar.
    """
    haberler = []
    target_url = hedef.get("target_url") or f"{hedef['base_url'].rstrip('/')}/haberler"
    
    try:
        resp = session.get(target_url, headers=DEFAULT_HEADERS, timeout=12, verify=False)
        if resp.status_code != 200:
            # Alternatif olarak ana sayfayı dene
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
            
            # Aynı domain altında ve haber/detay linki mi kontrolü
            if tam_url.startswith("http") and tam_url not in detay_linkleri:
                detay_linkleri.append(tam_url)
            if len(detay_linkleri) >= limit:
                break

        # Detay sayfalarını tara
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

                # Görseller (Yüksek Kaliteye Çevirme)
                gorseller = []
                for el in d_soup.select(seciciler.get("images", "img")):
                    raw_src = el.get("href") if el.name == "a" else (el.get("data-src") or el.get("src"))
                    if raw_src:
                        g = gorsel_kalitesini_artir(raw_src, hedef["base_url"])
                        if g:
                            gorseller.append(g)

                # Video Ayıklama
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
                kategori = kategori_tahmin_et(baslik, icerik)

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
                    "kurumTipi": hedef["kurum_tipi"],
                    "kaynakMotor": "SCRAPER",
                    "gorselUrls": temiz_gorseller,
                    "kapakGorseli": kapak_gorseli,
                    "videoUrl": video_url,
                    "kaynakUrl": detay_url,
                    "yayinTarihiMetin": tarih_metin,
                    "kategori": kategori,
                    "etiketler": [hedef["il_adi"], hedef["ilce_adi"], hedef["kurum_adi"], kategori],
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
# 6. OTONOM DÖNGÜ & AKIŞ ORKESTRASYONU
# ----------------------------------------------------------------------
def kurum_tara_is(hedef: dict, varsayilan_seciciler: dict, limit: int = 3) -> list:
    """
    Rapor mimarisindeki karar akışını tek bir kurum için işletir:
    1. [Resmi Kurum Web Siteleri]
    2. [RSS Var mı?]
       -> EVET: [RssService Engine]
       -> HAYIR: [Dynamic HTML Scraper]
    3. [Medya & Metin Ayrıştırma]
    4. [İl / İlçe Etiketleme]
    """
    with requests.Session() as session:
        has_rss, rss_url = rss_var_mi(hedef, session)
        if has_rss and rss_url:
            haberler = rss_servis_tara(hedef, rss_url, limit=limit)
        else:
            seciciler = hedef.get("seciciler") or varsayilan_seciciler
            haberler = html_scraper_tara(hedef, seciciler, session, limit=limit)
    return haberler

# ----------------------------------------------------------------------
# 7. HEDEFLERİ HAZIRLAMA (81 İl Valiliği & 922 İlçe Kaymakamlığı)
# ----------------------------------------------------------------------
def hedefleri_yukle(args) -> tuple[list, dict]:
    """
    turkiye_il_ilce.json ve kurum_listesi.json dosyalarını okuyarak
    kapsamlı hedef haritası üretir.
    """
    # 1. Şablonları oku
    with open("kurum_listesi.json", "r", encoding="utf-8") as f:
        config = json.load(f)

    templates = config.get("selector_templates", {})
    varsayilan_isay = templates.get("ISAY_GOV_TR", {
        "list_container": "div.haber-listesi a, div.duyuru-listesi a, .news-list a, .haberler a, a[href*='/haber']",
        "title": "h1.haber-baslik, h1.page-title, .detay-baslik h1, h1",
        "content": "div.haber-icerik, div.detay-icerik, #icerik-alani, article",
        "images": "div.haber-galeri a[href$='.jpg'], div.haber-galeri a[href$='.jpeg'], div.haber-icerik img, .galeri img",
        "video": "video source[src], iframe[src*='youtube'], a[href$='.mp4']",
        "date": "span.haber-tarih, .tarih, time"
    })
    varsayilan_belediye = templates.get("BELEDIYE_STANDART", varsayilan_isay)

    # 2. 81 İl ve İlçe Haritasını oku
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
        # 1-81 arasında belirli rotasyon aralığı (örneğin günün saatine göre)
        import datetime
        saat = datetime.datetime.now().hour
        rotasyon_grubu = (saat % 8) * 10 + 1
        secili_plakalar = set(range(rotasyon_grubu, min(rotasyon_grubu + 10, 82)))
    elif args.hepsi:
        secili_plakalar = set(range(1, 82))
    else:
        # Varsayılan mod: İlk 5 il valiliği + Adıyaman ve ilçeleri (güvenli başlangıç)
        secili_plakalar = {1, 2, 6, 34, 35}

    # A) 81 İl Valiliklerini Hedefe Ekle
    for plaka_str, il_bilgi in il_ilce_haritasi.items():
        plaka = int(plaka_str)
        if plaka not in secili_plakalar:
            continue
        il_adi = il_bilgi["il"]
        slug = il_bilgi["slug"]
        k_id = f"{plaka:02d}_merkez_valilik"

        hedef_listesi.append({
            "plaka": plaka,
            "il_adi": il_adi,
            "ilce_adi": "Merkez",
            "kurum_id": k_id,
            "kurum_adi": f"{il_adi} Valiliği",
            "kurum_tipi": "VALILIK",
            "base_url": f"http://www.{slug}.gov.tr",
            "target_url": f"http://www.{slug}.gov.tr/haberler",
            "has_rss": False,
            "rss_url": None,
            "seciciler": varsayilan_isay
        })

        # B) İlçelerin Kaymakamlıklarını Ekle
        for ilce in il_bilgi.get("ilceler", []):
            ilce_slug = turkce_slug(ilce)
            if not ilce_slug or ilce_slug == "merkez":
                continue
            
            # Eğer belirli ilçe filtresi varsa kontrol et
            if args.ilce and turkce_slug(args.ilce) != ilce_slug:
                continue

            k_ilce_id = f"{plaka:02d}_{ilce_slug}_kaymakamlik"
            hedef_listesi.append({
                "plaka": plaka,
                "il_adi": il_adi,
                "ilce_adi": ilce,
                "kurum_id": k_ilce_id,
                "kurum_adi": f"{ilce} Kaymakamlığı",
                "kurum_tipi": "KAYMAKAMLIK",
                "base_url": f"http://www.{ilce_slug}.gov.tr",
                "target_url": f"http://www.{ilce_slug}.gov.tr/haberler",
                "has_rss": False,
                "rss_url": None,
                "seciciler": varsayilan_isay
            })

    # C) Özel ve Listelenmiş Kurumları Ekle (kurum_listesi.json)
    for ozel in config.get("ozel_kurumlar", []):
        plaka = ozel["plaka"]
        if plaka in secili_plakalar:
            t_id = ozel.get("template_id", "ISAY_GOV_TR")
            seciciler = templates.get(t_id, varsayilan_isay)
            hedef_listesi.append({
                "plaka": plaka,
                "il_adi": ozel["il_adi"],
                "ilce_adi": ozel["ilce_adi"],
                "kurum_id": ozel["kurum_id"],
                "kurum_adi": ozel["kurum_adi"],
                "kurum_tipi": ozel["kurum_tipi"],
                "base_url": ozel["base_url"],
                "target_url": ozel["target_url"],
                "has_rss": ozel.get("has_rss", False),
                "rss_url": ozel.get("rss_url"),
                "seciciler": seciciler
            })

    # Duplicate kurum_id'leri temizle
    benzersiz_hedefler = {}
    for h in hedef_listesi:
        benzersiz_hedefler[h["kurum_id"]] = h

    return list(benzersiz_hedefler.values()), varsayilan_isay

# ----------------------------------------------------------------------
# 8. FIREBASE BAĞLANTISI VE YAZIM YÖNETİMİ
# ----------------------------------------------------------------------
def firebase_baglan(dry_run: bool):
    """
    Firebase Firestore istemcisini başlatır.
    Eğer anahtar yoksa veya dry_run seçilmişse mock mod döner.
    """
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

def haberleri_kaydet(haberler: list, db_client):
    """
    Toplanan haberleri Firebase Firestore 'saha_haberleri' koleksiyonuna
    500'lük Firestore batch sınırına uygun olarak yazar.
    """
    if not haberler:
        print("[KAYIT] Kaydedilecek haber bulunamadı.")
        return

    if db_client is None:
        # Yerel JSON'a yaz
        test_dosyasi = "saha_haberleri_test.json"
        with open(test_dosyasi, "w", encoding="utf-8") as f:
            json.dump(haberler, f, ensure_ascii=False, indent=2)
        print(f"[YEREL KAYIT] Toplam {len(haberler)} haber '{test_dosyasi}' dosyasına kaydedildi.")
        return

    # Firebase Firestore Batch Write
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
            # Firestore SERVER_TIMESTAMP ekle
            h_firestore = dict(h)
            h_firestore["olusturulmaTarihi"] = firestore.SERVER_TIMESTAMP
            batch.set(doc_ref, h_firestore, merge=True)
        batch.commit()
        print(f"[FIREBASE BATCH] {min(i + batch_boyutu, toplam)} / {toplam} haber kaydedildi.")

    print(f"[BAŞARILI] Toplam {toplam} haber Firestore '{KOLEKSIYON_ADI}' koleksiyonuna işlendi.")

# ----------------------------------------------------------------------
# 9. ANA ÇALIŞTIRICI (MAIN)
# ----------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Novra Saha Botu - 81 İl ve 922 İlçe Kamu Haber Takip Motoru")
    parser.add_argument("--plaka", type=int, help="Sadece belirtilen il plakasını tara (örn: 2)")
    parser.add_argument("--plaka-aralik", type=str, help="Plaka aralığını tara (örn: 1-10)")
    parser.add_argument("--ilce", type=str, help="Belirli bir ilçeyi tara (örn: kahta)")
    parser.add_argument("--rotasyon", action="store_true", help="Günün saatine göre rotasyonel il grubu tara")
    parser.add_argument("--hepsi", action="store_true", help="Tüm 81 il ve ilçeleri tara")
    parser.add_argument("--dry-run", action="store_true", help="Firebase yerine yerel JSON çıktısı al")
    parser.add_argument("--limit", type=int, default=3, help="Kurum başına çekilecek haber sayısı (varsayılan: 3)")
    parser.add_argument("--workers", type=int, default=12, help="Paralel iş parçacığı sayısı (varsayılan: 12)")
    args = parser.parse_args()

    print("=" * 70)
    print("NOVRA SAHA BOTU v1.4 BAŞLATILDI")
    print("Mimar: Muhammed Yasin KORKUT | Koleksiyon: saha_haberleri")
    print("=" * 70)

    # Hedef kurumları hazırla
    hedefler, varsayilan_seciciler = hedefleri_yukle(args)
    print(f"[HEDEF] Toplam {len(hedefler)} resmi kurum tarama havuzuna alındı.")

    # Firebase bağlantısını aç
    db_client = firebase_baglan(args.dry_run)

    # Paralel Tarama Başlat (Resmi Kurumlar -> [RSS Var mı?] -> RssService / Dynamic Scraper)
    toplanan_haberler = []
    print(f"[TARAMA] {args.workers} paralel worker ile tarama başlıyor...")

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
                    print(f" -> [+] {hedef['kurum_adi']}: {len(sonuclar)} haber çekildi.")
            except Exception as e:
                print(f" -> [-] {hedef['kurum_adi']} hata: {e}")

    print("-" * 70)
    print(f"[TAMAMLANDI] Toplam {len(toplanan_haberler)} resmi haber ve duyuru ayıklandı.")

    # Firebase Firestore'a yaz
    haberleri_kaydet(toplanan_haberler, db_client)

if __name__ == "__main__":
    main()
