# pip install operator
def cong(a, b):
    # Hàm tính tổng
    return a + b

def tru(a, b):
    # Hàm tính hiệu
    return a - b

def nhan(a, b):
    # Hàm tính tích
    return a * b

def chia(a, b):
    # Hàm tính thương
    if b == 0:
        raise ZeroDivisionError("Không thể chia cho 0")
    return a / b

def calculator():
    # Hàm chính của chương trình
    try:
        print("Chọn phép tính:")
        print("1. Cộng")
        print("2. Trừ")
        print("3. Nhân")
        print("4. Chia")
        choice = int(input("Nhập lựa chọn: "))
        
        num1 = float(input("Nhập số thứ nhất: "))
        num2 = float(input("Nhập số thứ hai: "))

        if choice == 1:
            print(f"{num1} + {num2} = {cong(num1, num2)}")
        elif choice == 2:
            print(f"{num1} - {num2} = {tru(num1, num2)}")
        elif choice == 3:
            print(f"{num1} * {num2} = {nhan(num1, num2)}")
        elif choice == 4:
            print(f"{num1} / {num2} = {chia(num1, num2)}")
        else:
            print("Lựa chọn không hợp lệ")
    except ZeroDivisionError as e:
        print(e)
    except ValueError:
        print("Nhập không hợp lệ")

if __name__ == '__main__':
    calculator()