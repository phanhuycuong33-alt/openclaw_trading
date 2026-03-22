# pip install flask
from flask import Flask, request, jsonify
import json

# Tạo ứng dụng Flask
app = Flask(__name__)

# Dữ liệu mẫu cho website
data = {
    "title": "Trang chủ",
    "content": "Chào mừng đến với trang web của tôi!"
}

# Trang chủ
@app.route('/', methods=['GET'])
def home():
    # Trả về dữ liệu trang chủ
    return jsonify(data)

# Trang về tôi
@app.route('/about', methods=['GET'])
def about():
    # Trả về thông tin về tôi
    return jsonify({"name": "Tôi", "age": 30})

# Trang liên hệ
@app.route('/contact', methods=['POST'])
def contact():
    try:
        # Nhận dữ liệu từ yêu cầu
        req_data = request.get_json()
        # Xử lý dữ liệu
        name = req_data.get('name')
        email = req_data.get('email')
        message = req_data.get('message')
        # Trả về thông báo thành công
        return jsonify({"message": "Cảm ơn bạn đã liên hệ!"})
    except Exception as e:
        # Xử lý lỗi
        return jsonify({"error": str(e)})

if __name__ == '__main__':
    # Chạy ứng dụng
    app.run(debug=True)