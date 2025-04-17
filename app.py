# app.py dosyasında

from flask import Flask, request, jsonify
import time
import traceback # Hata ayıklama için eklendi

app = Flask(__name__)

# Hafızada bekleyen taleplerin tutulacağı liste
bekleyen_talepler = []

# Öncelik sıralama fonksiyonu (değişiklik yok)
def hesapla_oncelik(istek):
    return istek.get("desired", 0) - istek.get("current", 0)

@app.route('/predict', methods=['POST'])
def predict():
    try:
        data = request.get_json()
        doluluk = data.get("doluluk", {})  # Örn: {"A": 1, "B": 0, "C": 0, "D": 1}
        requests_input = data.get("requests", []) # Android'den gelen yeni istek(ler)
        extra_requests = data.get("extra_requests", []) # Android'den gelen tüm liste (mevcut+yeni)

        print(f"📥 Gelen doluluk: {doluluk}")
        print(f"📥 Gelen requests_input: {requests_input}")
        print(f"📥 Gelen extra_requests: {extra_requests}")

        if not isinstance(extra_requests, list):
             return jsonify({"status": "error", "message": "'extra_requests' bir liste olmalı."}), 400

        tum_parklar = ["A", "B", "C", "D"]

        # --- 1. Tüm parklar dolu mu kontrolü ---
        # Not: doluluk.get(p, 1) -> Eğer park dolulukta yoksa, onu dolu (1) kabul et
        if all(doluluk.get(p, 1) == 1 for p in tum_parklar):
            print("🟥 Tüm park alanları dolu.")
            if requests_input:
                son_istek = requests_input[-1]
                # --- Kuyruğa Ekleme Mantığı ---
                # Aynı isteğin tekrar eklenmesini önle (isteğe bağlı)
                bekleyen_talepler[:] = [t for t in bekleyen_talepler if not (
                    t.get("parkid") == son_istek.get("parkid") and
                    t.get("current") == son_istek.get("current") and
                    t.get("desired") == son_istek.get("desired")
                )]
                # Zaman damgasıyla ekle
                son_istek['timestamp'] = time.time()
                bekleyen_talepler.append(son_istek)
                print(f"➕ Kuyruğa eklendi: {son_istek}")
                print(f"📊 Güncel Kuyruk: {bekleyen_talepler}")
                # --- Kuyruğa Ekleme Sonu ---
                return jsonify({
                    "status": "full",
                    "message": "Tüm park alanları dolu, talebiniz sıraya alındı.",
                    "saved_request": son_istek
                }), 200
            else:
                 # İstek yoksa ve her yer doluysa
                 return jsonify({"status": "full", "message": "Tüm park alanları dolu."}), 200

        # --- 2. Boş ve talepsiz parklar için dummy istek ekle ---
        # Bu adım, boş parkların da sıralamaya dahil edilmesini sağlar
        mevcut_park_talepleri = set(r.get("parkid") for r in extra_requests)
        dummy_eklendi = False
        for park in tum_parklar:
            # Sadece durumu 0 (boş) olan VE mevcut taleplerde olmayan parklar için dummy ekle
            if doluluk.get(park, 1) == 0 and park not in mevcut_park_talepleri:
                extra_requests.append({
                    "parkid": park,
                    "current": 0,
                    "desired": 0,
                    "is_dummy": True # Dummy olduğunu belirtmek faydalı olabilir
                })
                dummy_eklendi = True
        if dummy_eklendi:
            print(f"➕ Dummy eklendikten sonra extra_requests: {extra_requests}")

        # --- 3. Sadece BOŞ (doluluk == 0) parklara ait talepleri filtrele ---
        uygun_talepler = []
        for istek in extra_requests:
            park_id = istek.get("parkid")
            # Park ID var mı VE bu parkın doluluk durumu 0 (boş) mu?
            if park_id and doluluk.get(park_id, 1) == 0:
                uygun_talepler.append(istek)

        print(f"✅ Sadece boş parklara ait filtrelenmiş talepler: {uygun_talepler}")

        # --- 4. Filtrelenmiş listeyi önceliğe göre sırala ---
        # Eğer uygun_talepler boş değilse sırala
        if uygun_talepler:
            sirali_uygun = sorted(uygun_talepler, key=hesapla_oncelik, reverse=True)
            print(f"📊 Sıralanmış UYGUN talepler: {sirali_uygun}")
        else:
            # Eğer boş parklara ait hiç talep yoksa (ne gerçek ne dummy)
            sirali_uygun = []
            print("⚠️ Uygun (boş) parklara ait sıralanacak talep bulunamadı.")
            # Bu durumda belki yine kuyruğa alma işlemi yapılabilir veya özel durum döndürülebilir.
            # Şimdilik boş liste döndürelim, Android tarafı bunu handle etmeli.
            # Alternatif olarak, kullanıcıya özel mesaj:
            # return jsonify({
            #     "status": "no_available_slot_match",
            #     "message": "Boş park alanı bulunmasına rağmen eşleşen talep yok.", # Daha iyi mesaj lazım
            #     "sirali_istekler": []
            # })


        # --- 5. Sonucu Android'e gönder ---
        return jsonify({
            "status": "success",
            # Sadece boş parklara ait, sıralanmış talepleri gönder
            "sirali_istekler": sirali_uygun
        })

    except Exception as e:
        print(f"❌ Sunucu hatası: {str(e)}")
        traceback.print_exc() # Detaylı hata logu için
        return jsonify({
            "status": "error",
            "message": f"Sunucu hatası oluştu: {str(e)}"
        }), 500


# --- Diğer endpointler (/queued, /assign) ---
@app.route('/queued', methods=['GET'])
def queued_requests():
    # Kuyruktaki talepleri zamana göre sıralayarak döndürelim (en eski en başta)
    sirali_kuyruk = sorted(bekleyen_talepler, key=lambda item: item.get('timestamp', 0))
    return jsonify({
        "status": "ok",
        "queued": sirali_kuyruk # Sıralanmış kuyruk
    })

@app.route('/assign', methods=['POST'])
def assign_request():
    try:
        data = request.get_json()
        doluluk = data.get("doluluk", {})  # {"A": 1, "B": 0, ...}
        print(f"🅿️ /assign çağrıldı. Gelen doluluk: {doluluk}")
        print(f"🅿️ Mevcut kuyruk: {bekleyen_talepler}")

        tum_parklar = ["A", "B", "C", "D"]

        # Kuyruk boşsa işlem yapma
        if not bekleyen_talepler:
            print("🅿️ Kuyruk boş.")
            return jsonify({"status": "empty", "message": "Bekleyen talep yok"})

        # Kuyruktaki talepleri önceliğe göre sırala
        # Not: Kuyruktakilerin timestamp'i de var, ona göre de sıralanabilir.
        # Şimdilik önceliğe göre yapalım.
        kuyruk_sirali_oncelik = sorted(bekleyen_talepler, key=hesapla_oncelik, reverse=True)
        print(f"🅿️ Önceliğe göre sıralı kuyruk: {kuyruk_sirali_oncelik}")


        # Boş bir park bul
        atanan_park = None
        for parkid in tum_parklar:
            if doluluk.get(parkid, 1) == 0:  # Boş (0) olan ilk parkı bul
                atanan_park = parkid
                break # İlk boş parkı bulduk, döngüden çık

        if atanan_park:
            print(f"🅿️ Boş park bulundu: {atanan_park}")
            # En öncelikli talebi seç
            secilen_talep = kuyruk_sirali_oncelik[0]
            print(f"🅿️ Atanacak en öncelikli talep: {secilen_talep}")

            # Atama objesini oluştur
            atanan = {
                "parkid": atanan_park, # Boş bulunan park ID'si
                "current": secilen_talep["current"],
                "desired": secilen_talep["desired"],
                "original_parkid": secilen_talep.get("parkid"), # Orijinal istenen park (varsa)
                "queued_timestamp": secilen_talep.get("timestamp"), # Kuyruğa alınma zamanı
                "assigned_timestamp": time.time() # Atanma zamanı
            }

            # Talebi kuyruktan çıkar
            # ÖNEMLİ: Eğer birden fazla aynı talep olabilecekse, timestamp veya başka bir unique id ile silmek daha güvenli.
            # Şimdilik içeriğe göre siliyoruz.
            bekleyen_talepler.remove(secilen_talep)
            print(f"🅿️ Talep kuyruktan silindi. Kalan kuyruk: {bekleyen_talepler}")


            return jsonify({
                "status": "assigned",
                "assigned": atanan
            })
        else:
            print("🅿️ Boş park alanı bulunamadı.")
            return jsonify({
                "status": "full", # Boş park yoksa yine 'full' durumu
                "message": "Boş park alanı yok"
            })

    except Exception as e:
        print(f"❌ /assign Hatası: {str(e)}")
        traceback.print_exc()
        return jsonify({
            "status": "error",
            "message": f"Sunucu hatası: {str(e)}"
        }), 500


if __name__ == '__main__':
    # Debug modunu kapatıp host'u 0.0.0.0 yapmak production için daha uygun olabilir
    app.run(host='0.0.0.0', port=5000, debug=True) # Debug=True test sırasında faydalı