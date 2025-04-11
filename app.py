from flask import Flask, request, jsonify
import time

app = Flask(__name__)

# 🔁 Hafızada bekleyen taleplerin tutulacağı liste
bekleyen_talepler = []

@app.route('/predict', methods=['POST'])
def predict():
    try:
        data = request.get_json()

        doluluk = data.get("doluluk", {})
        requests = data.get("requests", [])

        print("📥 Gelen doluluk:", doluluk)
        print("📥 Gelen istekler:", requests)

        if not isinstance(requests, list):
            return jsonify({"status": "error", "message": "'requests' bir liste olmalı."}), 400

        tum_parklar = ["A", "B", "C", "D"]

        # 🟥 Eğer tüm park alanları doluysa sadece son isteği sıraya al
        if all(doluluk.get(p, 0) == 1 for p in tum_parklar):
            if requests:
                son_istek = requests[-1]
                bekleyen_talepler.append({
                    "parkid": son_istek["parkid"],
                    "current": son_istek["current"],
                    "desired": son_istek["desired"],
                    "timestamp": time.time()
                })
                print("🗃️ Tüm alanlar dolu, sadece son talep sıraya alındı!")
                return jsonify({
                    "status": "full",
                    "message": "Tüm park alanları dolu, talebiniz sıraya alındı.",
                    "saved_request": son_istek
                }), 200

        # ⚙️ Öncelik sıralama
        def hesapla_oncelik(istek):
            return (istek["desired"] - istek["current"])

        sirali = sorted(requests, key=hesapla_oncelik, reverse=True)

        return jsonify({
            "status": "success",
            "sirali_istekler": sirali
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": f"Sunucu hatası: {str(e)}"
        }), 500


# ✅ Bekleyen talepleri listele
@app.route('/queued', methods=['GET'])
def queued_requests():
    return jsonify({
        "status": "ok",
        "queued": bekleyen_talepler
    })


# ✅ Yeni: Boş alan varsa en öncelikli talebi atar ve siler
@app.route('/assign', methods=['POST'])
def assign_request():
    try:
        data = request.get_json()
        doluluk = data.get("doluluk", {})  # {"A": 1, "B": 0, ...}

        tum_parklar = ["A", "B", "C", "D"]

        for parkid in tum_parklar:
            if doluluk.get(parkid, 1) == 0:  # Bu alan boş
                if not bekleyen_talepler:
                    return jsonify({"status": "empty", "message": "Bekleyen talep yok"})

                # Talepleri sırala
                def oncelik(istek):
                    return istek["desired"] - istek["current"]

                sirali = sorted(bekleyen_talepler, key=oncelik, reverse=True)
                secilen = sirali[0]

                # ✅ Otomatik olarak yeni parkid’ye aktar
                atanan = {
                    "parkid": parkid,
                    "current": secilen["current"],
                    "desired": secilen["desired"],
                    "timestamp": time.time()
                }

                # Listeden çıkar
                bekleyen_talepler.remove(secilen)

                return jsonify({
                    "status": "assigned",
                    "assigned": atanan
                })

        return jsonify({
            "status": "full",
            "message": "Boş park alanı yok"
        })

    except Exception as e:
        return jsonify({
            "status": "error",
            "message": str(e)
        }), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
