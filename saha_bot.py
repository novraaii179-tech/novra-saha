import os
import json
import hashlib
import urllib3
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
from bs4 import BeautifulSoup
import feedparser
import firebase_admin
from firebase_admin import credentials, firestore

# Resmi kurum sitelerindeki SSL sertifika hatalarını yoksay
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 1. FIREBASE BAĞLANTISI
firebase_json_str = os.environ.get("FIREBASE_SERVICE_ACCOUNT")
if not firebase_json_str:
    raise ValueError("HATA: GitHub Secrets içinde FIREBASE_SERVICE_ACCOUNT bulunamadı!")

cred_dict = json.loads(firebase_json_str)
cred = credentials.Certificate(cred_dict)
if not firebase_admin._apps:
    firebase_admin.initialize_app(cred)

db = firestore.client()
KOLEKSIYON_ADI = "saha_haberleri"

# 2. TÜRKİYE 81 İL YERLEŞİK HARİTASI (Plaka: (İl Adı, Gov.tr Domain Kısa Adı))
ILLER_81 = {
    1: ("Adana", "adana"), 2: ("Adıyaman", "adiyaman"), 3: ("Afyonkarahisar", "afyonkarahisar"),
    4: ("Ağrı", "agri"), 5: ("Amasya", "amasya"), 6: ("Ankara", "ankara"),
    7: ("Antalya", "antalya"), 8: ("Artvin", "artvin"), 9: ("Aydın", "aydin"),
    10: ("Balıkesir", "balikesir"), 11: ("Bilecik", "bilecik"), 12: ("Bingöl", "bingol"),
    13: ("Bitlis", "bitlis"), 14: ("Bolu", "bolu"), 15: ("Burdur", "burdur"),
    16: ("Bursa", "bursa"), 17: ("Çanakkale", "canakkale"), 18: ("Çankırı", "cankiri"),
    19: ("Çorum", "corum"), 20: ("Denizli", "denizli"), 21: ("Diyarbakır", "diyarbakir"),
    22: ("Edirne", "edirne"), 23: ("Elazığ", "elazig"), 24: ("Erzincan", "erzincan"),
    25: ("Erzurum", "erzurum"), 26: ("Eskişehir", "eskisehir"), 27: ("Gaziantep", "gaziantep"),
    28: ("Giresun", "giresun"), 29: ("Gümüşhane", "gumushane"), 30: ("Hakkâri", "hakkari"),
    31: ("Hatay", "hatay"), 32: ("Isparta", "isparta"), 33: ("Mersin", "mersin"),
    34: ("İstanbul", "istanbul"), 35: ("İzmir", "izmir"), 36: ("Kars", "kars"),
    37: ("Kastamonu", "kastamonu"), 38: ("Kayseri", "kayseri"), 39: ("Kırklareli", "kirklareli"),
    40: ("Kırşehir", "kirsehir"), 41: ("Kocaeli", "kocaeli"), 42: ("Konya", "konya"),
    43: ("Kütahya", "kutahya"), 44: ("Malatya", "malatya"), 45: ("Manisa", "manisa"),
    46: ("Kahramanmaraş", "kahramanmaras"), 47: ("Mardin", "mardin"), 48: ("Muğla", "mugla"),
    49: ("Muş", "mus"), 50: ("Nevşehir", "nevsehir"), 51: ("Niğde", "nigde"),
    52: ("Ordu", "ordu"), 53: ("Rize", "rize"), 54: ("Sakarya", "sakarya"),
    55: ("Samsun", "samsun"), 56: ("Siirt", "siirt"), 57: ("Sinop", "sinop"),
    58: ("Sivas", "sivas"), 59: ("Tekirdağ", "tekirdag"), 60: ("Tokat", "tokat"),
    61: ("Trabzon", "trabzon"), 62: ("Tunceli", "tunceli"), 63: ("Şanlıurfa", "sanliurfa"),
    64: ("Uşak", "usak"), 65: ("Van", "van"), 66: ("Yozgat", "yozgat"),
    67: ("Zonguldak", "zonguldak"), 68: ("Aksaray", "aksaray"), 69: ("Bayburt", "bayburt"),
    70: ("Karaman", "karaman"), 71: ("Kırıkkale", "kirikkale"), 72: ("Batman", "batman"),
    73: ("Şırnak", "sirnak"), 74: ("Bartın", "bartin"), 75: ("Ardahan", "ardahan"),
    76: ("Iğdır", "igdir"), 77: ("Yalova", "yalova"), 78: ("Karabük", "karabuk"),
    79: ("Kilis", "kilis"), 80: ("Osmaniye", "osmaniye"), 81: ("Düzce", "duzce")
}

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
}

def id_uret(url: str) -> str:
    return hashlib.sha256(url.encode("utf-8")).hexdigest()[:28]

def gorsel_kalitesini_artir(img_url: str) -> str:
    return img_url.replace("/kucuk/", "/buyuk/").replace("_thumb", "")

def rss_tara(hedef: dict) -> list:
    """[RSS Var mı? -> Evet] RssService Engine"""
    haberler = []
    try:
        feed = feedparser.parse(hedef["rss_url"])
        for entry in feed.entries[:4]:
            link = entry.get("link", "").strip()
            baslik = entry.get("title", "").strip()
            if not link or not baslik:
                continue

            ozet_html = entry.get("summary", "") or entry.get("description", "")
            soup = BeautifulSoup(ozet_html, "html.parser")
            icerik = soup.get_text(separator=" ", strip=True)

            gorseller = []
            for img in soup.find_all("img"):
                src = img.get("src")
                if src:
                    gorseller.append(gorsel_kalitesini_artir(urljoin(hedef["base_url"], src)))

            haberler.append({
                "id": id_uret(link),
                "baslik": baslik,
                "icerik": icerik if len(icerik) > 10 else baslik,
                "ilKodu": hedef["plaka"],
                "ilAdi": hedef["il_adi"],
                "ilceAdi": hedef["ilce_adi"],
                "kurumId": hedef["kurum_id"],
                "kurumAdi": hedef["kurum_adi"],
                "kurumTipi": hedef["kurum_tipi"],
                "kaynakMotor": "RSS",
                "gorselUrls": list(set(gorseller)),
                "videoUrl": None,
                "kaynakUrl": link,
                "yayinTarihiMetin": entry.get("published", ""),
                "olusturulmaTarihi": firestore.SERVER_TIMESTAMP
            })
    except Exception as e:
        print(f"[RSS HATA] {hedef['kurum_adi']}: {e}")
    return haberler

def html_tara(hedef: dict, seciciler: dict) -> list:
    """[RSS Var mı? -> Hayır] Dynamic HTML Scraper"""
    haberler = []
    try:
        resp = requests.get(hedef["target_url"], headers=HEADERS, timeout=12, verify=False)
        if resp.status_code != 200:
            return haberler

        soup = BeautifulSoup(resp.text, "html.parser")
        link_etiketleri = soup.select(seciciler["list_container"])

        detay_linkleri = []
        for a in link_etiketleri:
            href = a.get("href")
            if not href or href.startswith("javascript") or href == "#":
                continue
            tam_url = urljoin(hedef["base_url"], href)
            if tam_url not in detay_linkleri and tam_url.startswith("http"):
                detay_linkleri.append(tam_url)
            if len(detay_linkleri) >= 3:  # Her kurumdan son 3 duyuruyu çek
                break

        for detay_url in detay_linkleri:
            try:
                d_resp = requests.get(detay_url, headers=HEADERS, timeout=12, verify=False)
                if d_resp.status_code != 200:
                    continue
                d_soup = BeautifulSoup(d_resp.text, "html.parser")

                baslik_el = d_soup.select_one(seciciler["title"])
                baslik = baslik_el.get_text(strip=True) if baslik_el else (d_soup.title.get_text(strip=True) if d_soup.title else "")
                if not baslik:
                    continue

                icerik_el = d_soup.select_one(seciciler["content"])
                icerik = icerik_el.get_text(separator=" ", strip=True) if icerik_el else ""
                if len(icerik) < 20:
                    # Fallback: Sayfadaki paragrafları birleştir
                    paragraflar = [p.get_text(strip=True) for p in d_soup.find_all("p") if len(p.get_text(strip=True)) > 30]
                    icerik = " ".join(paragraflar)
                if len(icerik) < 20:
                    continue

                # Görselleri Ayıkla
                gorseller = []
                for el in d_soup.select(seciciler["images"]):
                    raw_src = el.get("href") if el.name == "a" else (el.get("data-src") or el.get("src"))
                    if raw_src:
                        tam_gorsel = urljoin(hedef["base_url"], raw_src)
                        low = tam_gorsel.lower()
                        if not any(x in low for x in ["logo", "icon", "armasi", "bayrak", ".svg"]):
                            gorseller.append(gorsel_kalitesini_artir(tam_gorsel))

                # Video Ayıkla
                video_url = None
                if seciciler.get("video"):
                    v_el = d_soup.select_one(seciciler["video"])
                    if v_el:
                        v_raw = v_el.get("src") or v_el.get("href")
                        if v_raw:
                            video_url = urljoin(hedef["base_url"], v_raw)

                # Tarih Ayıkla
                tarih_metin = ""
                if seciciler.get("date"):
                    t_el = d_soup.select_one(seciciler["date"])
                    if t_el:
                        tarih_metin = t_el.get_text(strip=True)

                haberler.append({
                    "id": id_uret(detay_url),
                    "baslik": baslik,
                    "icerik": icerik[:3000],
                    "ilKodu": hedef["plaka"],
                    "ilAdi": hedef["il_adi"],
                    "ilceAdi": hedef["ilce_adi"],
                    "kurumId": hedef["kurum_id"],
                    "kurumAdi": hedef["kurum_adi"],
                    "kurumTipi": hedef["kurum_tipi"],
                    "kaynakMotor": "SCRAPER",
                    "gorselUrls": list(dict.fromkeys(gorseller))[:10],
                    "videoUrl": video_url,
                    "kaynakUrl": detay_url,
                    "yayinTarihiMetin": tarih_metin,
                    "olusturulmaTarihi": firestore.SERVER_TIMESTAMP
                })
            except Exception:
                continue
    except Exception as e:
        print(f"[SCRAPER HATA] {hedef['kurum_adi']}: {e}")
    return haberler

def hedefleri_hazirla():
    with open("kurum_listesi.json", "r", encoding="utf-8") as f:
        config = json.load(f)

    templates = config.get("selector_templates", {})
    varsayilan_isay = templates.get("ISAY_GOV_TR", {
        "list_container": "div.haber-listesi a, div.duyuru-listesi a, .news-list a, .haberler a, a[href*='/haber']",
        "title": "h1, .haber-baslik, .page-title",
        "content": "div.haber-icerik, div.detay-icerik, #icerik-alani, article",
        "images": "div.haber-galeri a[href$='.jpg'], div.haber-icerik img, .galeri img",
        "video": "video source[src], iframe[src*='youtube']",
        "date": "span.haber-tarih, .tarih, time"
    })

    hedef_haritasi = {}

    # A) 81 İlin Valiliklerini Otomatik Ekle
    for plaka, (il_adi, slug) in ILLER_81.items():
        k_id = f"{plaka:02d}_merkez_valilik"
        hedef_haritasi[k_id] = {
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
        }

    # B) kurum_listesi.json İçindeki Tüm İlçe Kaymakamlık ve Belediyelerini Ekle
    for il in config.get("iller", []):
        plaka = il["plaka"]
        il_adi = il["il_adi"]
        for ilce in il.get("ilceler", []):
            ilce_adi = ilce["ilce_adi"]
            for kurum in ilce.get("kurumlar", []):
                k_id = kurum["kurum_id"]
                t_id = kurum.get("template_id", "ISAY_GOV_TR")
                seciciler = kurum.get("custom_selectors") or templates.get(t_id, varsayilan_isay)
                hedef_haritasi[k_id] = {
                    "plaka": plaka,
                    "il_adi": il_adi,
                    "ilce_adi": ilce_adi,
                    "kurum_id": k_id,
                    "kurum_adi": kurum["kurum_adi"],
                    "kurum_tipi": kurum["kurum_tipi"],
                    "base_url": kurum["base_url"],
                    "target_url": kurum["target_url"],
                    "has_rss": kurum.get("has_rss", False),
                    "rss_url": kurum.get("rss_url"),
                    "seciciler": seciciler
                }

    return list(hedef_haritasi.values())

def calistir():
    hedefler = hedefleri_hazirla()
    print(f"Novra Saha Botu Başlatıldı! Toplam {len(hedefler)} resmi kurum taranıyor...")

    toplanan_haberler = []
    with ThreadPoolExecutor(max_workers=12) as executor:
        gelecek_isler = {
            executor.submit(
                rss_tara if (h["has_rss"] and h["rss_url"]) else html_tara,
                h,
                *([h["seciciler"]] if not (h["has_rss"] and h["rss_url"]) else [])
            ): h for h in hedefler
        }
        for future in as_completed(gelecek_isler):
            sonuc = future.result()
            if sonuc:
                toplanan_haberler.extend(sonuc)

    print(f"Tarama tamamlandı. Toplam {len(toplanan_haberler)} haber ayıklandı.")

    # Firebase Firestore 'saha_haberleri' Koleksiyonuna Toplu Yazım
    if toplanan_haberler:
        col_ref = db.collection(KOLEKSIYON_ADI)
        for i in range(0, len(toplanan_haberler), 400):
            batch = db.batch()
            grup = toplanan_haberler[i:i+400]
            for haber in grup:
                doc_ref = col_ref.document(haber["id"])
                batch.set(doc_ref, haber, merge=True)
            batch.commit()
        print(f"Başarılı! {len(toplanan_haberler)} haber Firebase '{KOLEKSIYON_ADI}' koleksiyonuna kaydedildi.")

if __name__ == "__main__":
    calistir()
