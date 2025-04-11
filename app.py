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
                son_istek = requests[-1]  # 🔻 Sadece en son gelen istek
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

        # ⚙️ Öncelik sıralama fonksiyonu
        def hesapla_oncelik(istek):
            kalan_sarj = istek["desired"] - istek["current"]
            parkid = istek["parkid"]
            dolu = doluluk.get(parkid, 0)
            return (kalan_sarj * 1.0) - (dolu * 100.0)

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

# ✅ Bekleyen talepleri listeleme endpoint'i
@app.route('/queued', methods=['GET'])
def queued_requests():
    now = time.time()
    ten_minutes_ago = now - 600  # 10 dakika önce

    aktif_bekleyenler = [
        item for item in bekleyen_talepler if item.get("timestamp", 0) >= ten_minutes_ago
    ]

    return jsonify({
        "status": "ok",
        "queued": aktif_bekleyenler
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)