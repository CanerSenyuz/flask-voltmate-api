from flask import Flask, request, jsonify

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

        # 🟥 Eğer tüm park alanları doluysa gelen istekleri sıraya al
        tum_parklar = ["A", "B", "C", "D"]
        if all(doluluk.get(p, 0) == 1 for p in tum_parklar):
            global bekleyen_talepler
            bekleyen_talepler.extend(requests)
            print("🗃️ Tüm alanlar dolu, talepler sıraya alındı!")
            return jsonify({
                "status": "full",
                "message": "Tüm park alanları dolu, talebiniz sıraya alındı.",
                "saved_requests": requests
            }), 200

        # ⚙️ Öncelik sıralama fonksiyonu
        def hesapla_oncelik(istek):
            kalan_sarj = istek["desired"] - istek["current"]
            parkid = istek["parkid"]
            dolu = doluluk.get(parkid, 0)
            return (kalan_sarj * 1.0) - (dolu * 100.0)

        # 🧮 Sıralama yapılır
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
    return jsonify({
        "status": "ok",
        "queued": bekleyen_talepler
    })

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
