# app.py (Güncellenmiş Hali)

from flask import Flask, request, jsonify
import time
import traceback # Hata ayıklama için eklendi

app = Flask(__name__)

# Hafızada bekleyen taleplerin tutulacağı liste
bekleyen_talepler = []

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
                # Sadece en son gelen isteği kuyruğa al
                son_istek = requests_input[-1]
                # --- Kuyruğa Ekleme ve Sıralama ---
                # Aynı isteğin tekrar eklenmesini önle (isteğe bağlı)
                bekleyen_talepler[:] = [t for t in bekleyen_talepler if not (
                    t.get("parkid") == son_istek.get("parkid") and
                    t.get("current") == son_istek.get("current") and
                    t.get("desired") == son_istek.get("desired")
                )]
                # Zaman damgasıyla ekle
                son_istek['timestamp'] = time.time()
                bekleyen_talepler.append(son_istek)
                print(f"➕ /predict - Kuyruğa eklendi: {son_istek}")

                # *** YENİ: Kuyruğu ekleme sonrası hemen sırala ***
                bekleyen_talepler.sort(key=hesapla_oncelik, reverse=True)
                print(f"📊 /predict - Kuyruk sıralandı. Güncel Sıralı Kuyruk: {bekleyen_talepler}")
                # --- Sıralama Sonu ---

                return jsonify({
                    "status": "full",
                    "message": "Tüm park alanları dolu, talebiniz sıraya alındı.",
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


# --- /assign Endpoint'i ---
@app.route('/assign', methods=['POST'])
def assign_request():
    try:
        data = request.get_json()
        doluluk = data.get("doluluk", {})  # Gelen doluluk (0/1 formatında bekleniyor)
        print(f"🅿️ /assign çağrıldı. Gelen doluluk (0/1): {doluluk}")
        # Kuyruk artık hep sıralı tutuluyor.
        print(f"🅿️ Mevcut Kuyruk (atanmadan önce, önceliğe göre sıralı olmalı): {bekleyen_talepler}")

        # Kuyruk boşsa işlem yapma
        if not bekleyen_talepler:
            print("🅿️ Kuyruk boş. Atama yapılamıyor.")
            return jsonify({"status": "empty", "message": "Bekleyen talep yok"})

        # *** SIRALAMA KISMI KALDIRILDI ***

        # Boş bir park bul
        atanan_park = None
        tum_parklar = ["A", "B", "C", "D"]
        print(f"🅿️ Boş park aranıyor... Gelen doluluk: {doluluk}")
        for parkid in tum_parklar:
            if doluluk.get(parkid, 1) == 0:  # Boş (0) olan ilk parkı bul
                atanan_park = parkid
                print(f"🅿️ Boş park bulundu: {atanan_park}")
                break # İlk boş parkı bulduk

        if atanan_park:
            # *** İLK ELEMANI AL VE LİSTEDEN ÇIKAR ***
            try:
                # .pop(0) hem ilk (en öncelikli) elemanı alır hem de listeden siler.
                secilen_talep = bekleyen_talepler.pop(0)
                print(f"🅿️ Atanacak en öncelikli talep (kuyruğun ilk elemanıydı): {secilen_talep}")
                print(f"🅿️ Talep kuyruktan silindi (pop(0) ile). Kalan kuyruk: {bekleyen_talepler}")
            except IndexError:
                 print(f"❌ Hata: Kuyruk boş olmasına rağmen atama bloğuna girildi?")
                 return jsonify({"status": "error", "message": "Kuyruk boşken eleman alınmaya çalışıldı."}), 500
            # *** ELEMAN ALMA VE SİLME SONU ***

            # Atama objesini oluştur
            atanan = {
                "parkid": atanan_park, # Boş bulunan park ID'si
                "current": secilen_talep.get("current"),
                "desired": secilen_talep.get("desired"),
                "original_parkid": secilen_talep.get("parkid"),
                "queued_timestamp": secilen_talep.get("timestamp"),
                "assigned_timestamp": time.time()
            }
            print(f"🅿️ Oluşturulan atama objesi: {atanan}")

            return jsonify({
                "status": "assigned",
                "assigned": atanan
            })
        else:
            print("🅿️ Atama için boş park alanı bulunamadı.")
            return jsonify({
                "status": "full",
                "message": "Boş park alanı yok"
            })

    except Exception as e:
        print(f"❌ /assign - Endpoint Hatası: {str(e)}")
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "message": f"Sunucu hatası: {str(e)}"
        }), 500


if __name__ == '__main__':
    # debug=True test sırasında faydalı, production'da False yapın
    # host='0.0.0.0' dışarıdan erişim için gereklidir (örn: Railway, Docker)
    app.run(host='0.0.0.0', port=5000, debug=True)