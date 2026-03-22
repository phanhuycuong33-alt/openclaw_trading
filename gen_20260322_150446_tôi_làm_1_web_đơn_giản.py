# pip install flask
from flask import Flask, request, jsonify

# Tạo ứng dụng Flask
app = Flask(__name__)

# Dữ liệu mẫu
data = {
    "1": {"name": "John", "age": 30},
    "2": {"name": "Alice", "age": 25}
}

# Trang chủ
@app.route("/", methods=["GET"])
def home():
    # Trả về thông điệp chào mừng
    return "Chào mừng đến với trang web của tôi!"

# Lấy tất cả dữ liệu
@app.route("/data", methods=["GET"])
def get_all_data():
    try:
        # Trả về tất cả dữ liệu
        return jsonify(data)
    except Exception as e:
        # Xử lý exception
        return str(e)

# Lấy dữ liệu theo ID
@app.route("/data/<id>", methods=["GET"])
def get_data_by_id(id):
    try:
        # Lấy dữ liệu theo ID
        return jsonify(data.get(id, "Không tìm thấy dữ liệu"))
    except Exception as e:
        # Xử lý exception
        return str(e)

# Thêm dữ liệu mới
@app.route("/data", methods=["POST"])
def add_data():
    try:
        # Lấy dữ liệu từ yêu cầu
        new_data = request.json
        # Thêm dữ liệu mới
        data[len(data) + 1] = new_data
        # Trả về thông điệp thành công
        return "Thêm dữ liệu thành công"
    except Exception as e:
        # Xử lý exception
        return str(e)

# Cập nhật dữ liệu
@app.route("/data/<id>", methods=["PUT"])
def update_data(id):
    try:
        # Lấy dữ liệu từ yêu cầu
        updated_data = request.json
        # Cập nhật dữ liệu
        if id in data:
            data[id] = updated_data
            # Trả về thông điệp thành công
            return "Cập nhật dữ liệu thành công"
        else:
            # Trả về thông điệp không tìm thấy dữ liệu
            return "Không tìm thấy dữ liệu"
    except Exception as e:
        # Xử lý exception
        return str(e)

# Xóa dữ liệu
@app.route("/data/<id>", methods=["DELETE"])
def delete_data(id):
    try:
        # Xóa dữ liệu
        if id in data:
            del data[id]
            # Trả về thông điệp thành công
            return "Xóa dữ liệu thành công"
        else:
            # Trả về thông điệp không tìm thấy dữ liệu
            return "Không tìm thấy dữ liệu"
    except Exception as e:
        # Xử lý exception
        return str(e)

if __name__ == '__main__':
    # Chạy ứng dụng
    app.run(debug=True)