from flask import Flask, request, jsonify

app = Flask(__name__)

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

        # ⚙️ Yeni skor hesaplama fonksiyonu
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

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000)
