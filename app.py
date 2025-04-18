# app.py (Güncellenmiş Hali)

from flask import Flask, request, jsonify
import time
import traceback # Hata ayıklama için eklendi

app = Flask(__name__)

# Hafızada bekleyen taleplerin tutulacağı liste
bekleyen_talepler = []

# Yeni eklenen: Son atamaların zaman damgalarını tutan sözlük
recent_assignments = {}
RECENT_ASSIGNMENT_TIMEOUT = 5 # Parkı kaç saniye kilitli tutalım? (Ayarlanabilir)
# --- Global Değişkenler Sonu ---

# --- Yardımcı Fonksiyon (Eski Kilitleri Temizlemek İçin) ---
def clean_recent_assignments():
    """Süresi dolmuş atama kilitlerini temizler."""
    global recent_assignments
    now = time.time()
    keys_to_delete = [park for park, timestamp in recent_assignments.items() if now - timestamp > RECENT_ASSIGNMENT_TIMEOUT]
    if keys_to_delete:
        print(f"🧹 Zaman aşımı: Şu park kilitleri kaldırılıyor: {keys_to_delete}")
        for key in keys_to_delete:
            del recent_assignments[key]
    # print(f"🧹 Temizlik sonrası kilitler: {recent_assignments}") # Debug için
# --- Yardımcı Fonksiyon Sonu ---

# Öncelik sıralama fonksiyonu
def hesapla_oncelik(istek):
    # Öncelik = İstenen Şarj - Mevcut Şarj (Yüksek fark = Yüksek öncelik)
    return istek.get("desired", 0) - istek.get("current", 0)

@app.route('/predict', methods=['POST'])
def predict():
    try:
        data = request.get_json()
        doluluk = data.get("doluluk", {})  # Örn: {"A": 1, "B": 0, "C": 0, "D": 1}
        requests_input = data.get("requests", []) # Android'den gelen yeni istek(ler)
        extra_requests = data.get("extra_requests", []) # Android'den gelen tüm liste (mevcut+yeni)

        print(f"📥 /predict - Gelen doluluk: {doluluk}")
        print(f"📥 /predict - Gelen requests_input: {requests_input}")
        print(f"📥 /predict - Gelen extra_requests: {extra_requests}")

        if not isinstance(extra_requests, list):
             return jsonify({"status": "error", "message": "'extra_requests' bir liste olmalı."}), 400

        tum_parklar = ["A", "B", "C", "D"]

        # --- 1. Tüm parklar dolu mu kontrolü ---
        if all(doluluk.get(p, 1) == 1 for p in tum_parklar):
            print("🟥 /predict - Tüm park alanları dolu.")
            if requests_input:
                son_istek = requests_input[-1]
                # --- Kuyruğa Ekleme & ID & Sıralama ---
                bekleyen_talepler[:] = [t for t in bekleyen_talepler if not (
                    # ... (aynı isteği önleme) ...
                )]
                # *** YENİ: Benzersiz ID olarak timestamp ekle ***
                request_timestamp_id = time.time()
                son_istek['timestamp'] = request_timestamp_id # Orijinal timestamp kalsın
                son_istek['request_id'] = request_timestamp_id # ID olarak da ekle
                # --- ID Ekleme Sonu ---

                bekleyen_talepler.append(son_istek)
                print(f"➕ /predict - Kuyruğa eklendi (ID'li): {son_istek}")

                bekleyen_talepler.sort(key=hesapla_oncelik, reverse=True)
                print(f"📊 /predict - Kuyruk sıralandı. ID'li Güncel Sıralı Kuyruk: {bekleyen_talepler}")

                return jsonify({
                    "status": "full",
                    "message": "Tüm park alanları dolu, talebiniz sıraya alındı.",
                    # *** YENİ: Kaydedilen isteğe ID ekle ***
                    "saved_request": son_istek
                }), 200
            else:
                 # İstek yoksa ve her yer doluysa
                 return jsonify({"status": "full", "message": "Tüm park alanları dolu."}), 200

        # --- 2. Boş ve talepsiz parklar için dummy istek ekle ---
        mevcut_park_talepleri = set(r.get("parkid") for r in extra_requests)
        dummy_eklendi = False
        for park in tum_parklar:
            if doluluk.get(park, 1) == 0 and park not in mevcut_park_talepleri:
                extra_requests.append({
                    "parkid": park,
                    "current": 0,
                    "desired": 0,
                    "is_dummy": True
                })
                dummy_eklendi = True
        if dummy_eklendi:
            print(f"➕ /predict - Dummy eklendikten sonra extra_requests: {extra_requests}")

        # --- 3. Sadece BOŞ (doluluk == 0) parklara ait talepleri filtrele ---
        uygun_talepler = []
        for istek in extra_requests:
            park_id = istek.get("parkid")
            if park_id and doluluk.get(park_id, 1) == 0:
                uygun_talepler.append(istek)
        print(f"✅ /predict - Sadece boş parklara ait filtrelenmiş talepler: {uygun_talepler}")

        # --- 4. Filtrelenmiş listeyi önceliğe göre sırala (Bu sıralama kalıyor) ---
        sirali_uygun = [] # Başlangıçta boş liste
        if uygun_talepler:
            sirali_uygun = sorted(uygun_talepler, key=hesapla_oncelik, reverse=True)
            print(f"📊 /predict - Sıralanmış UYGUN talepler (Android'e gönderilecek): {sirali_uygun}")
        else:
            print("⚠️ /predict - Uygun (boş) parklara ait sıralanacak talep bulunamadı.")

        # --- 5. Sonucu Android'e gönder ---
        return jsonify({
            "status": "success",
            "sirali_istekler": sirali_uygun # Sıralanmış uygun listeyi gönder
        })

    except Exception as e:
        print(f"❌ /predict - Sunucu hatası: {str(e)}")
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "message": f"Sunucu hatası oluştu: {str(e)}"
        }), 500


# --- /queued Endpoint'i ---
@app.route('/queued', methods=['GET'])
def queued_requests():
    # Kuyruk artık hep önceliğe göre sıralı tutuluyor.
    # Bu yüzden burada tekrar sıralamaya gerek yok. Direkt listeyi döndür.
    print(f"ℹ️ /queued çağrıldı. Mevcut (önceliğe göre sıralı) kuyruk: {bekleyen_talepler}")
    return jsonify({
        "status": "ok",
        "queued": bekleyen_talepler # Doğrudan sıralı listeyi döndür
    })


# --- /assign Endpoint'i (Güncellenmiş Hali) ---
@app.route('/assign', methods=['POST'])
def assign_request():
    global bekleyen_talepler, recent_assignments # Global değişkenlere erişim

    # Her çağrıda önce eski kilitleri temizle
    clean_recent_assignments()

    try:
        data = request.get_json()
        doluluk = data.get("doluluk", {})
        print(f"🅿️ /assign çağrıldı. Gelen doluluk (0/1): {doluluk}")
        print(f"🅿️ Mevcut Kuyruk: {bekleyen_talepler}")
        print(f"🅿️ Aktif Atama Kilitleri: {recent_assignments}")

        if not bekleyen_talepler:
             print("🅿️ Kuyruk boş. Atama yapılamıyor.")
             return jsonify({"status": "empty", "message": "Kuyruk boş."}), 200

        # --- Atanacak Parkı Bulma (Kilit Kontrolü ile) ---
        atanan_park = None
        secilen_talep_index = 0 # Kuyruk sıralı olduğu için ilk elemanı alacağız
        secilen_talep = bekleyen_talepler[secilen_talep_index]

        # Gelen doluluğa göre potansiyel boş parkları bul
        possible_parks = [p for p, status in doluluk.items() if status == 0]
        print(f"🅿️ Gelen doluluğa göre boş park adayları: {possible_parks}")

        # Boş parkları kontrol et
        for park_id in possible_parks:
            print(f"🅿️ Park {park_id} kontrol ediliyor...")
            # Eğer park yakın zamanda atanmışsa (kilitliyse), atla
            if park_id in recent_assignments:
                print(f"🅿️ Park {park_id} yakın zamanda atandığı için atlandı (kililtli).")
                continue

            # Boş ve kilitli olmayan ilk uygun parkı bulduk
            atanan_park = park_id
            print(f"🅿️ Boş ve kilitsiz park bulundu: {atanan_park}")
            break # Başka park aramaya gerek yok
        # --- Atanacak Parkı Bulma Sonu ---


        # --- Atama ve Yanıt Oluşturma ---
        if atanan_park is not None: # Uygun park bulunduysa
            # Seçilen talebi kuyruktan çıkar
            secilen_talep = bekleyen_talepler.pop(secilen_talep_index)
            print(f"🅿️ Atanacak talep: {secilen_talep}")
            print(f"🅿️ Talep kuyruktan silindi. Kalan kuyruk: {bekleyen_talepler}")

            # Parkı geçici olarak kilitle (zaman damgası ekle)
            recent_assignments[atanan_park] = time.time()
            print(f"🅿️ Park {atanan_park} {RECENT_ASSIGNMENT_TIMEOUT} saniye kilitlendi. Kilitler: {recent_assignments}")

            # Yanıt objesini oluştur
            atanan = {
                "parkid": atanan_park, # Atama yapılan park
                "current": secilen_talep.get("current"),
                "desired": secilen_talep.get("desired"),
                "original_parkid": secilen_talep.get("parkid"), # Orijinal tercih (gerekirse)
                "request_id": secilen_talep.get("request_id", -1.0),
                "assigned_timestamp": time.time()
            }
            print(f"🅿️ Android'e dönülecek atama objesi: {atanan}")
            return jsonify({"status": "assigned", "assigned": atanan})
        else:
            # Uygun park bulunamadı (ya hepsi doluydu ya da boş olanlar kilitliydi)
            print("🅿️ Uygun (boş ve kilitsiz) park bulunamadı.")
            return jsonify({"status": "full", "message": "Uygun park bulunamadı (ya dolu ya da yeni atandı)."}), 200
        # --- Atama ve Yanıt Sonu ---

    except Exception as e:
        print(f"❌ /assign Hatası: {e}")
        # import traceback # Detaylı hata için
        # traceback.print_exc()
        return jsonify({"status": "error", "message": str(e)}), 500


if __name__ == '__main__':
    # debug=True test sırasında faydalı, production'da False yapın
    # host='0.0.0.0' dışarıdan erişim için gereklidir (örn: Railway, Docker)
    app.run(host='0.0.0.0', port=5000, debug=True)