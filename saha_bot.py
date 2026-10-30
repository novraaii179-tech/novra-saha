"""
================================================================================
NOVRA A.İ. - Versiyon 1.4 Kapsamlı Proje
2. YENİ BOT: NOVRA SAHA (NOVRA FIELD BOT)
Kurucu: Kerem KURŞUNOĞLU
Yazılım Geliştiricileri: Muhammed Yasin KORKUT, Beyza KARAKAŞ
Telif Hakkı: Projenin tüm telif hakları Kurucu Kerem Kurşunoğlu'nun kuracağı adı 'Novra A.İ.' veya başka bir ad üstüne olacaktır.
Tarih: 15.10.2026

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
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
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
# ----------------------------------------------------------------------
# 2.1 IL VE ILCE HARITASI & AKILLI ILCE TESPIT MOTORU
# ----------------------------------------------------------------------
IL_ILCE_HARITASI: dict[str, list[str]] = {
    "Adıyaman": ["Kahta", "Besni", "Gölbaşı", "Gerger", "Sincik", "Çelikhan", "Tut", "Samsat"],
    "İstanbul": ["Kadıköy", "Beşiktaş", "Şişli", "Üsküdar", "Bakırköy", "Sarıyer", "Fatih", "Beyoğlu", "Maltepe", "Pendik", "Kartal", "Ataşehir", "Beylikdüzü", "Esenyurt", "Bağcılar", "Ümraniye", "Zeytinburnu", "Küçükçekmece", "Başakşehir", "Tuzla", "Silivri", "Çatalca", "Büyükçekmece", "Avcılar", "Arnavutköy", "Sancaktepe", "Sultanbeyli"],
    "Ankara": ["Çankaya", "Keçiören", "Yenimahalle", "Mamak", "Etimesgut", "Sincan", "Altındağ", "Pursaklar", "Polatlı", "Beypazarı", "Kızılcahamam"],
    "İzmir": ["Konak", "Karşıyaka", "Bornova", "Çiğli", "Buca", "Gaziemir", "Urla", "Karabağlar", "Bayraklı", "Menemen", "Torbalı", "Çeşme", "Aliağa", "Bergama", "Seferihisar", "Selçuk"],
    "Bursa": ["Nilüfer", "Osmangazi", "Yıldırım", "Mudanya", "Gemlik", "İnegöl", "Orhangazi", "Karacabey", "İznik"],
    "Antalya": ["Muratpaşa", "Konyaaltı", "Kepez", "Alanya", "Manavgat", "Kaş", "Kemer", "Serik", "Kumluca", "Finike", "Gazipaşa"],
    "Adana": ["Seyhan", "Çukurova", "Yüreğir", "Sarıçam", "Ceyhan", "Kozan"],
    "Konya": ["Selçuklu", "Meram", "Karatay", "Ereğli", "Akşehir", "Beyşehir"],
    "Gaziantep": ["Şahinbey", "Şehitkamil", "Nizip", "İslahiye"],
    "Şanlıurfa": ["Haliliye", "Eyyübiye", "Karaköprü", "Siverek", "Viranşehir", "Birecik", "Suruç", "Ceylanpınar"],
    "Muğla": ["Bodrum", "Fethiye", "Marmaris", "Menteşe", "Milas", "Datça"],
    "Aydın": ["Efeler", "Kuşadası", "Didim", "Söke", "Nazilli"],
    "Kocaeli": ["İzmit", "Gebze", "Darıca", "Körfez", "Gölcük"],
    "Tekirdağ": ["Süleymanpaşa", "Çorlu", "Çerkezköy"],
    "Balıkesir": ["Bandırma", "Edremit", "Ayvalık"],
    "Mersin": ["Tarsus", "Anamur", "Silifke"],
    "Hatay": ["İskenderun", "Antakya", "Dörtyol"],
    "Diyarbakır": ["Bağlar", "Kayapınar", "Sur", "Ergani", "Bismil"],
    "Trabzon": ["Ortahisar", "Akçaabat", "Yomra"],
    "Samsun": ["İlkadım", "Atakum", "Bafra", "Çarşamba"],
    "Manisa": ["Yunusemre", "Akhisar", "Turgutlu", "Salihli"],
    "Mardin": ["Artuklu", "Kızıltepe", "Midyat", "Nusaybin"],
    "Şırnak": ["Cizre", "Silopi"],
    "Hakkari": ["Yüksekova"],
    "Kahramanmaraş": ["Elbistan", "Afşin"]
}

def akilli_ilce_belirle(il_adi: str, mevcut_ilce: str, baslik: str, icerik: str, kurum_adi: str) -> str:
    """Haber metninde veya kurum adında geçen ilçe ismini tespit ederek Merkez fallback yerine nokta atışı ilçe atar."""
    if mevcut_ilce and mevcut_ilce != "Merkez":
        return mevcut_ilce

    ilceler = IL_ILCE_HARITASI.get(il_adi, [])
    if not ilceler:
        return mevcut_ilce or "Merkez"

    birlesik_metin = f"{kurum_adi} {baslik} {icerik[:500]}".lower().translate(TURKCE_HARF_HARITASI)
    for ilce in ilceler:
        ilce_norm = ilce.lower().translate(TURKCE_HARF_HARITASI)
        pattern = rf"\b{re.escape(ilce_norm)}(?:'[a-z]+|\s+kaymakamligi|\s+belediyesi|\s+ilcesi|\b)"
        if re.search(pattern, birlesik_metin):
            return ilce

    return mevcut_ilce or "Merkez"

# 3. MEDYA & METİN AYRIŞTIRMA (Gelişmiş Filtreleme & Kalite Motoru)
# ----------------------------------------------------------------------
ENGEL_GORSEL_KELIMELER = [
    "logo", "icon", "armasi", "arma", "bayrak", "avatar", "banner",
    "facebook", "twitter", "instagram", "youtube", "linkedin", "whatsapp",
    "footer", "header", ".svg", "reklam", "spacer", "pixel", "captcha",
    "favicon", "simge", "ataturk", "cimer", "edevlet", "cumhurbaskanligi",
    "bakanlik_yeni", "mansetresim", "paylasim.jpg", "yks-kurs", "kurumsal/",
    "tasarim/", "webfiles/logolar", "images/projeler/", "fontbuyut",
    "fontkucult", "fontnormal", "yazdir"
]

ENGEL_LINK_KELIMELER = [
    "iletisim", "kurumsal", "hakkimizda", "tarihce", "mevzuat", "teskilat",
    "misyon", "vizyon", "rehber", "eczaneler", "organizasyon", "etik-",
    "ic-kontrol", "arabuluculuk", "zimmet", "bordro", "lbys", "hekimim",
    "randevu", "laboratuvar", "rapor-sonuclari", "nasil-giderim", "yonetim",
    "muduru", "baskanlar", "vali", "kaymakam", "sube-mudurlugu", "mudurlugu",
    "birimi", "vezn", "tahsilat", "ebelediye", "meclis", "muhtar", "kvkk",
    "hesap-verilebilirlik", "nikah", "vergi", "otobus", "mezbahane", "halk-ekmek",
    "bize-ulasin", "beyaz-masa", "ekspertiz", "yapi-denetim", "taziye",
    "sosyal-market", "kentrehberi", "arsiv.aspx", "haberarsivi", "/menu/",
    "/kategori/", "/haberler", "/duyurular", "/ihaleler", "guncel-haberler",
    "etkinlikler", "projelerimiz", "devam-edenler", "planlanan-projeler",
    "tamamlanmis-projeler", "birimler", "gelir", "kadin-aile", "afet_isleri",
    "sosyal-yardim", "ozel-kalem", "basin-yayin", "bilgi-islem", "fen-isleri",
    "kultur-sosyal", "su-kanalizasyon", "temizlik-isleri", "imar-sehircilik",
    "zabita", "itfaiye", "mali-hizmetler", "mezarliklar", "park-bahceler",
    "ruhsat-denetleme", "ulasim-hizmetleri", "veteriner", "yazi-isleri",
    "yapi-kontrol", "strateji-gelistirme", "planlama", "hal-isleri",
    "iklim-degisikligi", "insan-kaynaklari", "destek-hizmetler", "hukuk-isleri"
]

def style_icinden_url_ayikla(style_str: str) -> str:
    """CSS style='background-image:url(...)' içinden görsel URL'sini ayıklar."""
    if not style_str:
        return ""
    eslesme = re.search(r"url\(\s*['\"]?([^'\")\s]+)['\"]?\s*\)", style_str, flags=re.IGNORECASE)
    return eslesme.group(1).strip() if eslesme else ""

def gorsel_kalitesini_artir(raw_url: str, base_url: str) -> str:
    """Küçük boyutlu önizlemeleri yüksek çözünürlüklü orijinal görsellere yükseltir."""
    if not raw_url:
        return ""
    
    temiz_raw = html.unescape(raw_url.strip())
    if temiz_raw.startswith(("data:", "javascript:", "mailto:", "tel:", "#")):
        return ""

    # CSS url(...) sarmalayıcısı varsa ayıkla
    if "url(" in temiz_raw.lower():
        temiz_raw = style_icinden_url_ayikla(temiz_raw)
        if not temiz_raw:
            return ""

    tam_url = urljoin(base_url, temiz_raw)
    low = tam_url.lower()

    if any(k in low for k in ENGEL_GORSEL_KELIMELER):
        return ""

    # Sağlık Bakanlığı dosyaism.saglik.gov.tr/Resim/.../1/... küçük resmini /0/ (orijinal) yap
    tam_url = re.sub(r"(/Resim/\d+)/1/", r"\1/0/", tam_url)

    # /kucuk/ -> /buyuk/
    tam_url = re.sub(r"/(?:kucuk|thumb|thumbnail|min)/", "/buyuk/", tam_url, flags=re.IGNORECASE)
    
    # _thumb, _kucuk uzantılarını temizle
    tam_url = re.sub(r"[_-](?:thumb|thumbnail|kucuk|min|k)\.(jpg|jpeg|png|webp)", r".\1", tam_url, flags=re.IGNORECASE)

    # Query string'deki küçültme parametrelerini temizle (ISAY ?mode=resize&width=800, Tarım ?RenditionID=2 vb.)
    parsed = urlparse(tam_url)
    if parsed.query:
        qs = parse_qs(parsed.query)
        silinecek_parametreler = {"w", "h", "width", "height", "resize", "quality", "fit", "mode", "renditionid"}
        filtrelenmis_qs = {k: v for k, v in qs.items() if k.lower() not in silinecek_parametreler}
        yeni_query = "&".join(f"{k}={v[0]}" for k, v in filtrelenmis_qs.items())
        tam_url = parsed._replace(query=yeni_query).geturl()

    return tam_url

def eleman_gorsellerini_cikar(el, sayfa_url: str) -> list[str]:
    """Bir HTML elemanından (img, a, div[style] vb.) olası tüm görsel URL'lerini çıkarır."""
    adaylar = []
    if el.name == "a":
        href = el.get("href") or ""
        if re.search(r"\.(?:jpg|jpeg|png|webp)(?:\?.*)?$", href, flags=re.IGNORECASE) or el.has_attr("data-fancybox") or "/Resim/" in href:
            adaylar.append(href)
        for ic_img in el.find_all("img"):
            for attr in ("data-src", "data-original", "data-lazy-src", "src"):
                if ic_img.get(attr):
                    adaylar.append(ic_img.get(attr))
    elif el.name == "img":
        # Önce yüksek çözünürlüklü data-src, sonra src
        for attr in ("data-src", "data-original", "data-lazy-src", "src", "srcset"):
            val = el.get(attr)
            if val:
                if attr == "srcset":
                    val = val.split(",")[0].strip().split(" ")[0]
                adaylar.append(val)
    else:
        if el.get("data-background"):
            adaylar.append(el.get("data-background"))
        if el.get("style") and "url(" in el.get("style", "").lower():
            adaylar.append(style_icinden_url_ayikla(el.get("style")))

    sonuclar = []
    for raw in adaylar:
        g = gorsel_kalitesini_artir(raw, sayfa_url)
        if g and g not in sonuclar:
            sonuclar.append(g)
    return sonuclar

def kart_kapak_gorseli_bul(a_etiketi, sayfa_url: str) -> str:
    """Haber listesi sayfasındaki kart/link elemanından kapak görselini veya arkaplan resmini yakalar."""
    search_roots = [a_etiketi]
    if a_etiketi.parent:
        search_roots.append(a_etiketi.parent)
        if a_etiketi.parent.parent:
            search_roots.append(a_etiketi.parent.parent)

    for root in search_roots:
        for img in root.find_all("img"):
            g_list = eleman_gorsellerini_cikar(img, sayfa_url)
            if g_list:
                return g_list[0]
        for st_el in root.find_all(style=True):
            u = style_icinden_url_ayikla(st_el.get("style", ""))
            if u:
                g = gorsel_kalitesini_artir(u, sayfa_url)
                if g:
                    return g
    return ""

def video_url_normallestir(raw_video_url: str, base_url: str) -> str:
    """Bulunan video URL'sini temiz ve oynatılabilir tam URL formatına dönüştürür."""
    if not raw_video_url:
        return None
    v_url = html.unescape(raw_video_url.strip())
    if v_url.startswith(("javascript:", "mailto:", "#")):
        return None
    v_url = urljoin(base_url, v_url)
    low = v_url.lower()

    if "youtube.com" in low or "youtu.be" in low:
        if "/embed/" in v_url:
            yt_id = v_url.split("/embed/")[1].split("?")[0].split("&")[0].strip("/")
            if yt_id:
                return f"https://www.youtube.com/watch?v={yt_id}"
        elif "youtu.be/" in v_url:
            yt_id = v_url.split("youtu.be/")[1].split("?")[0].split("&")[0].strip("/")
            if yt_id:
                return f"https://www.youtube.com/watch?v={yt_id}"
        return v_url

    if any(k in low for k in ["vimeo.com", "dailymotion.com", ".mp4", ".webm", ".mov", ".m4v", ".m3u8"]):
        return v_url

    return v_url

def video_ayikla(soup: BeautifulSoup, base_url: str) -> str:
    """HTML içinden video kaynaklarını (HTML5 video, YouTube, Vimeo, Dailymotion, Meta, MP4) ayıklar."""
    # 1. HTML5 Video & Source etiketleri
    for v in soup.find_all("video"):
        for attr in ("src", "data-src"):
            if v.get(attr):
                norm = video_url_normallestir(v.get(attr), base_url)
                if norm:
                    return norm
        for s in v.find_all("source"):
            for attr in ("src", "data-src"):
                if s.get(attr):
                    norm = video_url_normallestir(s.get(attr), base_url)
                    if norm:
                        return norm

    # 2. iframe / embed Video (YouTube, Vimeo, Dailymotion, Sosyal Medya Video)
    for iframe in soup.find_all(["iframe", "embed", "object"]):
        src = iframe.get("src") or iframe.get("data-src") or iframe.get("data-lazy-src") or iframe.get("data")
        if not src:
            continue
        low = src.lower()
        if any(k in low for k in ["youtube.com", "youtu.be", "vimeo.com", "dailymotion.com", "player.", "/video", ".mp4", ".m3u8"]):
            norm = video_url_normallestir(src, base_url)
            if norm:
                return norm

    # 3. OpenGraph / Twitter Video Meta Etiketleri
    for meta in soup.find_all("meta", attrs={"property": re.compile(r"og:video|twitter:player", re.I)}):
        content = meta.get("content")
        if content:
            norm = video_url_normallestir(content, base_url)
            if norm:
                return norm

    # 4. Doğrudan Video Linkleri veya data-video / onclick özellikleri
    for a in soup.find_all(["a", "div", "span"]):
        for attr in ("href", "data-video", "data-src", "data-url"):
            val = a.get(attr)
            if val and re.search(r"\.(?:mp4|webm|mov|m4v|m3u8)(?:\?.*)?$", val, flags=re.IGNORECASE):
                norm = video_url_normallestir(val, base_url)
                if norm:
                    return norm

    # 5. Script veya sayfa içi gömülü MP4 / YouTube Embed araması (Fallback)
    html_str = str(soup)
    yt_match = re.search(r"https?://(?:www\.)?youtube\.com/embed/([a-zA-Z0-9_-]{6,})", html_str)
    if yt_match:
        return f"https://www.youtube.com/watch?v={yt_match.group(1)}"

    mp4_match = re.search(r"(['\"])((?:https?:)?//[^'\"]+?\.mp4(?:\?[^'\"]*)?|/[^'\"]+?\.mp4(?:\?[^'\"]*)?)\1", html_str, flags=re.IGNORECASE)
    if mp4_match:
        aday_mp4 = mp4_match.group(2)
        if "popup" not in aday_mp4.lower():
            return video_url_normallestir(aday_mp4, base_url)

    return None

def youtube_kapak_resmi_uret(video_url: str) -> str:
    """Haberde görsel yoksa ancak YouTube videosu varsa yüksek çözünürlüklü video kapağını döndürür."""
    if not video_url:
        return None
    eslesme = re.search(r"(?:v=|/embed/|youtu\.be/)([a-zA-Z0-9_-]{6,})", video_url)
    if eslesme:
        return f"https://img.youtube.com/vi/{eslesme.group(1)}/hqdefault.jpg"
    return None

def sayfa_gorsellerini_topla(d_soup: BeautifulSoup, seciciler: dict, sayfa_url: str, liste_kapak: str = "") -> list[str]:
    """
    Detay sayfasından (ve gerekirse liste kartından) haberle ilgili tüm yüksek çözünürlüklü görselleri toplar.
    """
    gorseller = []

    # 1. Seçici şablonundaki özel görsel/galeri alanlarını tara
    img_secici = seciciler.get("images", "img")
    for el in d_soup.select(img_secici):
        # Son haberler / benzer haberler widget'ları içindeki resimleri hariç tut
        el_id = (el.get("id") or "").lower()
        if "sonhaberler" in el_id or "benzer" in el_id:
            continue
        for g in eleman_gorsellerini_cikar(el, sayfa_url):
            if g not in gorseller:
                gorseller.append(g)

    # 2. Genel galeri ve içerik kapsayıcılarını tara (ISAY, MEB, Tarım, Sağlık, AFAD, Belediye ortak yapıları)
    ek_seciciler = (
        ".swiper-gallery img, .zgLarge a[data-fancybox], .zgLarge img, "
        ".adasoftPhotoBox a, .adasoftPhotoBox img, .fgaleri img, .ortala img, "
        ".content-image img, .article-detay a[data-fancybox], .article-detay img, "
        ".itemBody img, .gallery-image, .hbrImg, .icerik img, .detail-content-container img"
    )
    for el in d_soup.select(ek_seciciler):
        el_id = (el.get("id") or "").lower()
        if "sonhaberler" in el_id or "benzer" in el_id:
            continue
        for g in eleman_gorsellerini_cikar(el, sayfa_url):
            if g not in gorseller:
                gorseller.append(g)

    # 3. Liste sayfasındaki kartta yakalanan kapak görselini dahil et
    if liste_kapak:
        if liste_kapak not in gorseller:
            # Eğer detayda hiç görsel bulunamadıysa veya kapak resmi olarak en başa eklenmesi gerekiyorsa
            gorseller.insert(0, liste_kapak)

    # 4. Hâlâ görsel bulunamadıysa OpenGraph / Twitter Image meta etiketlerine bak
    if not gorseller:
        for meta in d_soup.find_all("meta", attrs={"property": re.compile(r"og:image|twitter:image", re.I)}):
            m_url = meta.get("content")
            if m_url:
                g = gorsel_kalitesini_artir(m_url, sayfa_url)
                if g and g not in gorseller:
                    gorseller.append(g)

    # Aynı görselin farklı varyasyonlarını (örn: küçük/büyük veya tekrar eden dosya yollarını) tekilleştir
    benzersiz_gorseller = []
    gorulen_yollar = set()
    for g in gorseller:
        parsed_g = urlparse(g)
        anahtar = parsed_g.netloc.lower() + parsed_g.path.lower()
        if anahtar not in gorulen_yollar:
            gorulen_yollar.add(anahtar)
            benzersiz_gorseller.append(g)

    return benzersiz_gorseller[:10]

def metin_temizle(ham_metin: str) -> str:
    """HTML etiketlerinden ve gereksiz boşluklardan arındırılmış temiz metin üretir."""
    if not ham_metin:
        return ""
    metin = html.unescape(ham_metin)
    metin = metin.replace("\xa0", " ").replace("Â", "")
    metin = re.sub(r"\s+", " ", metin)
    return metin.strip()

# ----------------------------------------------------------------------
# 4. [ RSS Var mı? ] KARAR MOTORU (Auto-Discovery Engine)
# ----------------------------------------------------------------------
def rss_var_mi(hedef: dict, session: requests.Session) -> tuple[bool, str]:
    """Resmi kurum web sitesinde RSS beslemesi olup olmadığını otomatik tespit eder."""
    if hedef.get("has_rss") and hedef.get("rss_url"):
        return True, hedef["rss_url"]

    # MEB sitelerinin RSS beslemelerinde gerçek haber görseli yerine sabit 'mansetresim.png' bulunduğu için
    # MEB kurumlarında doğrudan zengin HTML Scraper motorunu kullanmak görsel/video kaydını garanti eder.
    if hedef.get("kurum_tipi") == "MEB":
        return False, None

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
                    tam_rss = urljoin(base, href)
                    if "mansetresim" not in tam_rss and "meb_iys_dosyalar/xml/rss" not in tam_rss:
                        return True, tam_rss
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
# 5. [ RssService Engine ] (XML Parser & Media + Detay Sayfası Zenginleştirme)
# ----------------------------------------------------------------------
def rss_servis_tara(hedef: dict, rss_url: str, seciciler: dict = None, session: requests.Session = None, limit: int = 4) -> list:
    """[RSS Var mı? -> Evet] RssService Engine: XML ayrıştırma ve zengin medya çıkarma."""
    haberler = []
    seciciler = seciciler or {}
    try:
        if session is not None:
            resp = session.get(rss_url, headers=DEFAULT_HEADERS, timeout=10, verify=False)
            feed = feedparser.parse(resp.content)
        else:
            feed = feedparser.parse(rss_url, request_headers=DEFAULT_HEADERS)

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

            # Medya Ayrıştırma: Görseller (Enclosures + media:content + media:thumbnail + img)
            gorseller = []
            for enc in entry.get("enclosures", []):
                href = enc.get("href") or enc.get("url")
                if href and (enc.get("type", "").startswith("image/") or re.search(r"\.(?:jpg|jpeg|png|webp)", href, re.I)):
                    g = gorsel_kalitesini_artir(href, link)
                    if g:
                        gorseller.append(g)

            for m_item in entry.get("media_content", []) + entry.get("media_thumbnail", []):
                m_url = m_item.get("url")
                if m_url:
                    g = gorsel_kalitesini_artir(m_url, link)
                    if g:
                        gorseller.append(g)

            for img in soup.find_all("img"):
                for g in eleman_gorsellerini_cikar(img, link):
                    gorseller.append(g)

            # Video Ayrıştırma
            video_url = None
            for enc in entry.get("enclosures", []):
                href = enc.get("href") or enc.get("url")
                if href and (enc.get("type", "").startswith("video/") or re.search(r"\.(?:mp4|webm|mov|m3u8)", href, re.I)):
                    video_url = video_url_normallestir(href, link)
                    break
            if not video_url:
                video_url = video_ayikla(soup, link)

            # Eğer RSS içinde görsel veya video eksikse, haberin detay sayfasına gidip medyayı tamamla
            if (not gorseller or not video_url) and session is not None:
                try:
                    d_resp = session.get(link, headers=DEFAULT_HEADERS, timeout=10, verify=False)
                    if d_resp.status_code == 200:
                        d_soup = BeautifulSoup(d_resp.text, "html.parser")
                        detay_url_gercek = d_resp.url or link
                        if not gorseller:
                            gorseller = sayfa_gorsellerini_topla(d_soup, seciciler, detay_url_gercek)
                        if not video_url:
                            video_url = video_ayikla(d_soup, detay_url_gercek)
                        if len(icerik_metin) < 80:
                            icerik_el = d_soup.select_one(seciciler.get("content", "article, .icerik, .haber-icerik"))
                            if icerik_el:
                                tam_metin = metin_temizle(icerik_el.get_text(separator=" ", strip=True))
                                if len(tam_metin) > len(icerik_metin):
                                    icerik_metin = tam_metin
                except Exception:
                    pass

            if not gorseller and video_url:
                yt_kapak = youtube_kapak_resmi_uret(video_url)
                if yt_kapak:
                    gorseller.append(yt_kapak)

            yayin_tarihi = entry.get("published", "") or entry.get("updated", "")
            temiz_gorseller = list(dict.fromkeys(gorseller))[:10]
            kapak_gorseli = temiz_gorseller[0] if temiz_gorseller else ""
            haber_id = id_uret(link)

            # Kategori ve Kurum Analizi
            kat_kod, kat_ad, nihai_kt, kt_ad = kategori_ve_kurum_belirle(baslik, icerik_metin, hedef["kurum_tipi"])
            nihai_ilce = akilli_ilce_belirle(hedef["il_adi"], hedef.get("ilce_adi", ""), baslik, icerik_metin, hedef.get("kurum_adi", ""))

            ozet_kisa = icerik_metin[:240] + ("..." if len(icerik_metin) > 240 else "")
            ana_medya_url = video_url or kapak_gorseli
            medya_tipi = "VIDEO" if video_url else ("IMAGE" if kapak_gorseli else "NONE")

            haberler.append({
                "id": haber_id,
                "baslik": baslik,
                "ozet": ozet_kisa,
                "icerik": icerik_metin[:5000],
                "ilKodu": hedef["plaka"],
                "ilAdi": hedef["il_adi"],
                "ilceAdi": nihai_ilce,
                "kurumId": hedef["kurum_id"],
                "kurumAdi": hedef["kurum_adi"],
                "kurumTipi": nihai_kt,
                "kurumTipiAdi": kt_ad,
                "kaynakMotor": "RSS",
                "gorselUrls": temiz_gorseller,
                "gorselUrl": kapak_gorseli,
                "kapakGorseli": kapak_gorseli,
                "resimUrl": kapak_gorseli,
                "videoUrl": video_url or "",
                "videoUrls": [video_url] if video_url else [],
                "medyaVarMi": bool(temiz_gorseller or video_url),
                "kaynakUrl": link,
                "yayinTarihiMetin": yayin_tarihi,
                "kategori": kat_kod,
                "kategoriAdi": kat_ad,
                "etiketler": [hedef["il_adi"], nihai_ilce, kt_ad, kat_ad],
                "aktifMi": True,
                "onayDurumu": "YAYINDA",
                "okunmaSayisi": 0,
                "begeniSayisi": 0,
                # Otonom Montaj (AutoPilot) & Çapraz Platform (Web + Android) Standart Alanları
                "is_auto_montaged": False,
                "il": hedef["il_adi"],
                "ilce": nihai_ilce,
                "city": hedef["il_adi"],
                "district": nihai_ilce,
                "title": baslik,
                "description": icerik_metin[:5000],
                "imageUrl": kapak_gorseli,
                "gorsel_url": kapak_gorseli,
                "mediaUrl": ana_medya_url or "",
                "mediaType": medya_tipi,
                "source": hedef["kurum_adi"],
                "sourceName": hedef["kurum_adi"],
                "sourceUrl": link
            })
    except Exception as e:
        print(f"[RSS MOTOR HATA] {hedef['kurum_adi']}: {e}")
    return haberler

# ----------------------------------------------------------------------
# 6. [ Dynamic HTML Scraper ] (JSoup / Headless Worker / BS4)
# ----------------------------------------------------------------------
def haber_linki_gecerli_mi(tam_url: str, base_url: str) -> bool:
    """Bir URL'nin menü/kurumsal sayfa değil, gerçek bir haber/duyuru detay linki olup olmadığını denetler."""
    if not tam_url.startswith("http"):
        return False

    parsed_base = urlparse(base_url)
    parsed_url = urlparse(tam_url)

    # Farklı bir domaine giden dış linkleri (tccb.gov.tr, turkiye.gov.tr, sosyal medya vb.) ele
    base_domain = parsed_base.netloc.lower().replace("www.", "")
    url_domain = parsed_url.netloc.lower().replace("www.", "")
    if base_domain not in url_domain and url_domain not in base_domain:
        return False

    path = parsed_url.path.strip("/")
    if not path or len(path) < 5:
        return False

    low_path = path.lower()
    if low_path.endswith((".pdf", ".doc", ".docx", ".xls", ".xlsx", ".zip", ".rar", ".jpg", ".png")):
        return False

    # Bilinen sabit kurumsal menü yollarını filtrele
    son_parca = low_path.split("/")[-1]
    if son_parca in ENGEL_LINK_KELIMELER or any(low_path == k.strip("/") for k in ENGEL_LINK_KELIMELER):
        return False

    # Haber linkleri genellikle ya '/icerik/', '/Haber/', '/TR-' içerir ya da tireli anlamlı bir slug'a sahiptir
    if any(p in low_path for p in ["/icerik/", "/haber/", "/duyuru/", "tr-"]):
        if any(k in low_path for k in ["kurumsal.html", "teskilat-semasi", "misyonumuz", "vizyonumuz", "yonetim.html", "il-saglik-muduru", "baskanlar.html", "iletisim.html", "mevzuat.html", "formlar.html", "gruplandirma.html", "mobil-bolgeler", "birimi.html", "baskanligi.html", "nobet-listesi", "eczaneler.html", "telefon-rehberi", "aile-hekimim", "bu-test-nerede", "bordro.html", "lbys.html", "zimmet-sorgulama", "bilgi-guvenligi", "arabuluculuk", "ic-kontrol", "etik-", "organizasyon-kitabi", "satinalma-duyurulari", "nasil-giderim", "randevu-sistemi", "laboratuvar-sonuclari", "rapor-sonuclari"]):
            return False
        return True

    # Tire içeren ve en az 2 kelimeli slug yapısı (örn: valimiz-sayin-... veya adiyaman-belediyemiz-...)
    if "-" in son_parca and len(son_parca) >= 12:
        if any(son_parca.endswith(ek) for ek in ["-mudurlugu", "-kaymakami", "-komutanligi", "-baskanligi", "-birimi", "-komisyonu", "-standartlari", "-basvurusu", "-listesi", "-tarihcesi", "-valilerimiz"]):
            return False
        return True

    return False

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

        aktif_liste_url = resp.url or target_url
        soup = BeautifulSoup(resp.text, "html.parser")
        link_etiketleri = soup.select(seciciler.get("list_container", "a"))

        detay_adaylari = []  # [(tam_url, liste_kapak_gorseli, kart_basligi)]
        gorulen_linkler = set()

        for a in link_etiketleri:
            href = (a.get("href") or "").strip()
            if not href or href.startswith(("javascript", "mailto:", "tel:", "#")):
                continue
            tam_url = urljoin(aktif_liste_url, href)
            if tam_url in gorulen_linkler:
                continue
            if not haber_linki_gecerli_mi(tam_url, aktif_liste_url):
                continue

            gorulen_linkler.add(tam_url)
            liste_kapak = kart_kapak_gorseli_bul(a, aktif_liste_url)
            kart_baslik = metin_temizle(a.get("title") or a.get_text(separator=" ", strip=True))
            detay_adaylari.append((tam_url, liste_kapak, kart_baslik))
            if len(detay_adaylari) >= limit * 2:
                break

        # Eğer özel seçiciyle yeterli link bulunamadıysa tüm <a> etiketlerinden geçerli haber linklerini tara
        if not detay_adaylari:
            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                if not href or href.startswith(("javascript", "mailto:", "tel:", "#")):
                    continue
                tam_url = urljoin(aktif_liste_url, href)
                if tam_url not in gorulen_linkler and haber_linki_gecerli_mi(tam_url, aktif_liste_url):
                    gorulen_linkler.add(tam_url)
                    liste_kapak = kart_kapak_gorseli_bul(a, aktif_liste_url)
                    kart_baslik = metin_temizle(a.get("title") or a.get_text(separator=" ", strip=True))
                    detay_adaylari.append((tam_url, liste_kapak, kart_baslik))
                    if len(detay_adaylari) >= limit * 2:
                        break

        for detay_url, liste_kapak, kart_baslik in detay_adaylari:
            if len(haberler) >= limit:
                break
            try:
                d_resp = session.get(detay_url, headers=DEFAULT_HEADERS, timeout=12, verify=False)
                if d_resp.status_code != 200:
                    continue
                gercek_detay_url = d_resp.url or detay_url
                d_soup = BeautifulSoup(d_resp.text, "html.parser")

                # Başlık
                baslik = ""
                baslik_el = d_soup.select_one(seciciler.get("title", "h1, h2.page-title, h2.main-title, h3.page-title, .page-content-header h5"))
                if baslik_el:
                    # ISAY h2.page-title içinde span varsa sadece span metnini al
                    span_el = baslik_el.find("span")
                    baslik = span_el.get_text(strip=True) if span_el else baslik_el.get_text(strip=True)
                if not baslik and d_soup.title:
                    baslik = d_soup.title.get_text(strip=True).split(" - ")[-1]
                if not baslik and kart_baslik and kart_baslik.lower() != "devamını oku":
                    baslik = kart_baslik
                baslik = metin_temizle(baslik)
                if not baslik:
                    continue

                # İçerik
                icerik = ""
                icerik_el = d_soup.select_one(seciciler.get("content", "div.icerik, .article-detay, .itemBody, .page-content-body-hc, article"))
                if icerik_el:
                    icerik = icerik_el.get_text(separator=" ", strip=True)
                if len(icerik) < 30:
                    paragraflar = [p.get_text(strip=True) for p in d_soup.find_all("p") if len(p.get_text(strip=True)) > 25]
                    icerik = " ".join(paragraflar)
                icerik = metin_temizle(icerik)
                if len(icerik) < 20:
                    icerik = baslik

                # Görseller (Detay sayfası + Galeri + Liste kartı kapağı)
                temiz_gorseller = sayfa_gorsellerini_topla(d_soup, seciciler, gercek_detay_url, liste_kapak=liste_kapak)

                # Video (Seçici + Genel HTML5/YouTube/Vimeo/MP4 tarayıcı)
                video_url = None
                if seciciler.get("video"):
                    for v_el in d_soup.select(seciciler["video"]):
                        v_src = v_el.get("src") or v_el.get("data-src") or v_el.get("href")
                        if v_src:
                            video_url = video_url_normallestir(v_src, gercek_detay_url)
                            if video_url:
                                break
                if not video_url:
                    video_url = video_ayikla(d_soup, gercek_detay_url)

                # Haberde fotoğraf yoksa ancak YouTube videosu varsa video kapağını görsel olarak ekle
                if not temiz_gorseller and video_url:
                    yt_kapak = youtube_kapak_resmi_uret(video_url)
                    if yt_kapak:
                        temiz_gorseller.append(yt_kapak)

                # Tarih
                tarih_metin = ""
                if seciciler.get("date"):
                    t_el = d_soup.select_one(seciciler["date"])
                    if t_el:
                        tarih_metin = metin_temizle(t_el.get_text(strip=True))

                kapak_gorseli = temiz_gorseller[0] if temiz_gorseller else ""
                haber_id = id_uret(gercek_detay_url)

                # Kategori ve Kurum Analizi
                kat_kod, kat_ad, nihai_kt, kt_ad = kategori_ve_kurum_belirle(baslik, icerik, hedef["kurum_tipi"])
                nihai_ilce = akilli_ilce_belirle(hedef["il_adi"], hedef.get("ilce_adi", ""), baslik, icerik, hedef.get("kurum_adi", ""))

                ozet_kisa = icerik[:240] + ("..." if len(icerik) > 240 else "")
                ana_medya_url = video_url or kapak_gorseli
                medya_tipi = "VIDEO" if video_url else ("IMAGE" if kapak_gorseli else "NONE")

                haberler.append({
                    "id": haber_id,
                    "baslik": baslik,
                    "ozet": ozet_kisa,
                    "icerik": icerik[:5000],
                    "ilKodu": hedef["plaka"],
                    "ilAdi": hedef["il_adi"],
                    "ilceAdi": nihai_ilce,
                    "kurumId": hedef["kurum_id"],
                    "kurumAdi": hedef["kurum_adi"],
                    "kurumTipi": nihai_kt,
                    "kurumTipiAdi": kt_ad,
                    "kaynakMotor": "SCRAPER",
                    "gorselUrls": temiz_gorseller,
                    "gorselUrl": kapak_gorseli,
                    "kapakGorseli": kapak_gorseli,
                    "resimUrl": kapak_gorseli,
                    "videoUrl": video_url or "",
                    "videoUrls": [video_url] if video_url else [],
                    "medyaVarMi": bool(temiz_gorseller or video_url),
                    "kaynakUrl": gercek_detay_url,
                    "yayinTarihiMetin": tarih_metin,
                    "kategori": kat_kod,
                    "kategoriAdi": kat_ad,
                    "etiketler": [hedef["il_adi"], nihai_ilce, kt_ad, kat_ad],
                    "aktifMi": True,
                    "onayDurumu": "YAYINDA",
                    "okunmaSayisi": 0,
                    "begeniSayisi": 0,
                    # Otonom Montaj (AutoPilot) & Çapraz Platform (Web + Android) Standart Alanları
                    "is_auto_montaged": False,
                    "il": hedef["il_adi"],
                    "ilce": nihai_ilce,
                    "city": hedef["il_adi"],
                    "district": nihai_ilce,
                    "title": baslik,
                    "description": icerik[:5000],
                    "imageUrl": kapak_gorseli,
                    "gorsel_url": kapak_gorseli,
                    "mediaUrl": ana_medya_url or "",
                    "mediaType": medya_tipi,
                    "source": hedef["kurum_adi"],
                    "sourceName": hedef["kurum_adi"],
                    "sourceUrl": gercek_detay_url
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
    seciciler = hedef.get("seciciler") or varsayilan_seciciler
    with requests.Session() as session:
        has_rss, rss_url = rss_var_mi(hedef, session)
        if has_rss and rss_url:
            haberler = rss_servis_tara(hedef, rss_url, seciciler=seciciler, session=session, limit=limit)
        else:
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
        doc_refs = [col_ref.document(h["id"]) for h in grup]
        mevcut_harita = {}
        try:
            for snap in db_client.get_all(doc_refs):
                if snap.exists:
                    mevcut_harita[snap.id] = snap.to_dict() or {}
        except Exception:
            pass

        for h in grup:
            doc_ref = col_ref.document(h["id"])
            h_firestore = dict(h)
            mevcut_veri = mevcut_harita.get(h["id"])
            if mevcut_veri is not None:
                # Daha önce otonom montajlandıysa (is_auto_montaged == True) kesinlikle sıfırlama!
                h_firestore["is_auto_montaged"] = bool(mevcut_veri.get("is_auto_montaged", False))
                h_firestore["guncellenmeTarihi"] = firestore.SERVER_TIMESTAMP
                if "olusturulmaTarihi" not in mevcut_veri:
                    h_firestore["olusturulmaTarihi"] = firestore.SERVER_TIMESTAMP
                if "createdAt" not in mevcut_veri:
                    h_firestore["createdAt"] = firestore.SERVER_TIMESTAMP
                if "silinmeTarihi" not in mevcut_veri:
                    h_firestore["silinmeTarihi"] = silinme_zamani
            else:
                # Yeni haber dokümanı: AutoPilot kuyruğuna girmesi için is_auto_montaged = False
                h_firestore["is_auto_montaged"] = False
                h_firestore["olusturulmaTarihi"] = firestore.SERVER_TIMESTAMP
                h_firestore["createdAt"] = firestore.SERVER_TIMESTAMP
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

