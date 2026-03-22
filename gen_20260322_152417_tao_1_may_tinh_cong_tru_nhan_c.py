# pip install numpy
import numpy as np

# Hàm thực hiện phép tính cộng
def cong(a, b):
    # Trả về kết quả cộng
    return a + b

# Hàm thực hiện phép tính trừ
def tru(a, b):
    # Trả về kết quả trừ
    return a - b

# Hàm thực hiện phép tính nhân
def nhan(a, b):
    # Trả về kết quả nhân
    return a * b

# Hàm thực hiện phép tính chia
def chia(a, b):
    # Kiểm tra chia cho 0
    if b == 0:
        raise ZeroDivisionError("Không thể chia cho 0")
    # Trả về kết quả chia
    return a / b

# Hàm chính
def main():
    try:
        # Nhập số thứ nhất
        a = float(input("Nhập số thứ nhất: "))
        # Nhập phép tính
        phep_tinh = input("Nhập phép tính (+, -, *, /): ")
        # Nhập số thứ hai
        b = float(input("Nhập số thứ hai: "))

        # Thực hiện phép tính
        if phep_tinh == "+":
            ket_qua = cong(a, b)
        elif phep_tinh == "-":
            ket_qua = tru(a, b)
        elif phep_tinh == "*":
            ket_qua = nhan(a, b)
        elif phep_tinh == "/":
            ket_qua = chia(a, b)
        else:
            raise ValueError("Phép tính không hợp lệ")

        # In kết quả
        print(f"{a} {phep_tinh} {b} = {ket_qua}")

    except ZeroDivisionError as e:
        print(f"Lỗi: {e}")
    except ValueError as e:
        print(f"Lỗi: {e}")
    except Exception as e:
        print(f"Lỗi không xác định: {e}")

if __name__ == '__main__':
    main()