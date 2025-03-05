import streamlit as st
import os
import re
import hashlib
import requests
import tempfile
import io
import json
from PIL import Image
from PyPDF2 import PdfReader, PdfWriter
import google.generativeai as genai

# Khởi tạo session state
if 'logged_in' not in st.session_state:
    st.session_state.logged_in = False
if 'username' not in st.session_state:
    st.session_state.username = ""

# URL của file users.json trên GitHub (raw content)
USERS_FILE_URL = "https://raw.githubusercontent.com/thayphuctoan/pconvert/refs/heads/main/user.json"
# URL của file activated.txt trên GitHub (raw content)
ACTIVATION_FILE_URL = "https://raw.githubusercontent.com/thayphuctoan/pconvert/main/check-convert"

# Hàm lấy danh sách người dùng từ GitHub
@st.cache_data(ttl=300)  # Cache 5 phút
def get_users():
    try:
        response = requests.get(USERS_FILE_URL)
        if response.status_code == 200:
            return json.loads(response.text)
        else:
            st.error(f"Không thể lấy danh sách người dùng từ GitHub. Status code: {response.status_code}")
            return {}
    except Exception as e:
        st.error(f"Lỗi khi lấy danh sách người dùng: {str(e)}")
        return {}

# Hàm lấy danh sách ID đã kích hoạt từ GitHub
@st.cache_data(ttl=300)  # Cache 5 phút
def get_activated_ids():
    try:
        response = requests.get(ACTIVATION_FILE_URL)
        if response.status_code == 200:
            return response.text.strip().split('\n')
        else:
            st.error(f"Không thể lấy danh sách ID kích hoạt từ GitHub. Status code: {response.status_code}")
            return []
    except Exception as e:
        st.error(f"Lỗi khi lấy danh sách ID kích hoạt: {str(e)}")
        return []

# Hàm xác thực người dùng
def authenticate_user(username, password):
    users = get_users()
    if username in users and users[username] == password:
        return True
    return False

# Hàm tạo hardware ID cố định từ username
def generate_hardware_id(username):
    # Tạo hardware ID từ username - luôn giống nhau cho cùng một username
    hardware_id = hashlib.md5(username.encode()).hexdigest().upper()
    formatted_id = '-'.join([hardware_id[i:i+8] for i in range(0, len(hardware_id), 8)])
    return formatted_id + "-Premium"

class PDFConverterApp:
    def __init__(self, username=""):
        self.api_key = ""
        self.file_path = None
        self.uploaded_file = None
        self.model = None
        self.pdf_text = ""
        self.split_files = []
        self.activation_status = "CHƯA KÍCH HOẠT"
        self.username = username
        self.hardware_id = self.get_hardware_id()
        
    def get_hardware_id(self):
        # Tạo hardware ID cố định từ username
        if self.username:
            return generate_hardware_id(self.username)
        
        # Fallback nếu không có username
        return "NOT-AUTHENTICATED-USER"

    def check_activation(self):
        activated_ids = get_activated_ids()
        
        if self.hardware_id in activated_ids:
            self.activation_status = "ĐÃ KÍCH HOẠT"
            return True
        else:
            self.activation_status = "CHƯA KÍCH HOẠT"
            return False

    def set_api_key(self, api_key):
        self.api_key = api_key
        if self.api_key:
            genai.configure(api_key=self.api_key)
            self.update_model(use_flash_model=st.session_state.get('use_flash_model', False))
            return True
        return False

    def update_model(self, use_flash_model=False):
        try:
            # URL cho 2 model
            model_1_url = "https://raw.githubusercontent.com/thayphuctoan/pconvert/refs/heads/main/pconvert-model"
            model_2_url = "https://raw.githubusercontent.com/thayphuctoan/pconvert/refs/heads/main/pconvert-model-2"
            
            # Đọc tên model dựa vào tham số
            if use_flash_model:
                response = requests.get(model_1_url)
                model_name = response.text.strip()
            else:
                response = requests.get(model_2_url)
                model_name = response.text.strip()
            
            generation_config = {
                "temperature": 0.1,
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 8192,
                "response_mime_type": "text/plain",
            }
            self.model = genai.GenerativeModel(model_name=model_name, generation_config=generation_config)
        except Exception as e:
            st.error(f"Error updating model: {e}")
            # Fallback to default model if cannot fetch from GitHub
            model_name = "gemini-2.0-flash-thinking-exp-1219"
            generation_config = {
                "temperature": 0.1,
                "top_p": 0.95,
                "top_k": 40,
                "max_output_tokens": 8192,
                "response_mime_type": "text/plain",
            }
            self.model = genai.GenerativeModel(model_name=model_name, generation_config=generation_config)

    # Các phương thức khác như trong mã nguồn gốc
    def process_pdf(self, uploaded_file, split_large_pdfs=False):
        # Save the uploaded file to a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.pdf') as temp_file:
            temp_file.write(uploaded_file.getvalue())
            temp_file_path = temp_file.name
        
        pdf = PdfReader(temp_file_path)
        total_pages = len(pdf.pages)
        
        if total_pages <= 10 or not split_large_pdfs:
            self.uploaded_file = genai.upload_file(path=temp_file_path, display_name="Uploaded File")
            return True, "File uploaded successfully. You can now convert it to text."
        else:
            result = self.split_pdf(pdf, total_pages, temp_file_path)
            os.unlink(temp_file_path)  # Remove the temporary file
            return result

    def process_image(self, uploaded_file):
        # Save the uploaded file to a temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as temp_file:
            temp_file.write(uploaded_file.getvalue())
            temp_file_path = temp_file.name
        
        self.uploaded_file = genai.upload_file(path=temp_file_path, display_name="Uploaded File")
        os.unlink(temp_file_path)  # Remove the temporary file
        return True, "Image uploaded successfully. You can now convert it to text."

    def split_pdf(self, pdf, total_pages, pdf_path):
        st.write("Splitting PDF into smaller chunks...")
        
        chunk_size = 10
        num_chunks = (total_pages + chunk_size - 1) // chunk_size
        
        base_name = os.path.splitext(pdf_path)[0]
        self.split_files = []
        
        for i in range(num_chunks):
            start_page = i * chunk_size
            end_page = min((i + 1) * chunk_size, total_pages)
            
            output = PdfWriter()
            for page in range(start_page, end_page):
                output.add_page(pdf.pages[page])
            
            output_filename = f"{base_name}_part{i+1}.pdf"
            with open(output_filename, "wb") as output_stream:
                output.write(output_stream)
            
            self.split_files.append(output_filename)
        
        return True, f"PDF split into {num_chunks} parts. Ready for conversion."

    def convert_pdf_to_text(self, is_latex_mcq=False):
        if not self.model:
            return False, "Please set the API Key first."
        
        if not self.uploaded_file and not self.split_files:
            return False, "Please upload a file first."
        
        if is_latex_mcq:
            prompt = """
            Hãy nhận diện và gõ lại [CHÍNH XÁC] PDF thành văn bản, tất cả công thức Toán Latex, bọc trong dấu $
            [TUYỆT ĐỐI] không thêm nội dung khác ngoài nội dung PDF, [CHỈ ĐƯỢC PHÉP] gõ lại nội dung PDF thành văn bản.
            1. Chuyển bảng (table) thông thường sang cấu trúc như này cho tôi, còn bảng biến thiên thì không chuyển
            \\begin{tabular}{|c|c|c|c|c|c|}
            \\hline$x$ & -2 & -1 & 0 & 1 & 2 \\\\
            \\hline$y=x^2$ & 4 & 1 & 0 & 1 & 4 \\\\
            \\hline
            \\end{tabular}
            2. Hãy bỏ cấu trúc in đậm của Markdown trong kết quả (bỏ dấu *)
            3. Chuyển nội dung văn bản trong file sang cấu trúc Latex với câu hỏi trắc nghiệm
            """
        else:
            prompt = """
            Hãy nhận diện và gõ lại [CHÍNH XÁC] PDF thành văn bản, tất cả công thức Toán Latex, bọc trong dấu $
            [TUYỆT ĐỐI] không thêm nội dung khác ngoài nội dung PDF, [CHỈ ĐƯỢC PHÉP] gõ lại nội dung PDF thành văn bản.
            """
        
        if self.split_files:
            return self.convert_split_files(prompt, is_latex_mcq)
        else:
            return self.convert_single_file(prompt, is_latex_mcq)

    def convert_single_file(self, prompt, is_latex_mcq=False):
        try:
            with st.spinner("Converting file to text..."):
                response = self.model.generate_content([self.uploaded_file, prompt])
                if is_latex_mcq:
                    result_text = response.text
                else:
                    result_text = self.process_formulas(response.text)
                return True, result_text
        except Exception as e:
            return False, f"Error converting file: {str(e)}"

    def convert_split_files(self, prompt, is_latex_mcq=False):
        try:
            all_results = []
            
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            for i, file_path in enumerate(self.split_files):
                status_text.write(f"Converting part {i+1}/{len(self.split_files)}...")
                
                # Create a Gemini "uploaded file" from the file
                uploaded_part = genai.upload_file(path=file_path, display_name=f"Part {i+1}")
                
                # Convert the file
                response = self.model.generate_content([uploaded_part, prompt])
                all_results.append(response.text)
                
                # Update progress
                progress_bar.progress((i+1)/len(self.split_files))
            
            # Combine results
            combined_text = "\n\n--- End of Part ---\n\n".join(all_results)
            
            # Process if needed
            if not is_latex_mcq:
                combined_text = self.process_formulas(combined_text)
            
            # Clean up split files
            for file_path in self.split_files:
                os.remove(file_path)
            self.split_files = []
            
            return True, combined_text
        except Exception as e:
            return False, f"Error converting split files: {str(e)}"

    def process_formulas(self, text):
        def process_math_content(match):
            content = match.group(1)
            content = content.replace('π', '\\pi')
            content = re.sub(r'√(\d+)', r'\\sqrt{\1}', content)
            content = re.sub(r'√\{([^}]+)\}', r'\\sqrt{\1}', content)
            content = content.replace('≠', '\\neq')
            content = content.replace('*', '')
            return f'${content}$'

        text = re.sub(r'\$(.+?)\$', process_math_content, text, flags=re.DOTALL)
        return text

def login_page():
    st.title("P_Convert - Đăng nhập")
    
    username = st.text_input("Tên đăng nhập")
    password = st.text_input("Mật khẩu", type="password")
    
    if st.button("Đăng nhập"):
        if authenticate_user(username, password):
            st.session_state.logged_in = True
            st.session_state.username = username
            
            # Hiển thị hardware ID để thêm vào danh sách kích hoạt
            hardware_id = generate_hardware_id(username)
            st.success(f"Đăng nhập thành công! Hardware ID của bạn là: {hardware_id}")
            st.info("Vui lòng liên hệ quản trị viên để kích hoạt hardware ID này nếu chưa được kích hoạt.")
            
            # Hiển thị nút để tải lại trang
            if st.button("Tiếp tục"):
                st.experimental_rerun()
        else:
            st.error("Tên đăng nhập hoặc mật khẩu không đúng!")
    
    st.write("Chưa có tài khoản? Vui lòng liên hệ quản trị viên để được cấp.")

def main_app():
    # Khởi tạo ứng dụng với username - Điều này đảm bảo hardware ID cố định
    if 'app' not in st.session_state or st.session_state.app.username != st.session_state.username:
        st.session_state.app = PDFConverterApp(st.session_state.username)
    app = st.session_state.app
    
    st.title(f"P_Convert v1.3 - Chào mừng {st.session_state.username}")
    st.subheader("Chuyển PDF/Image sang văn bản không lỗi công thức Toán")
    
    # API Key section
    with st.expander("Cài đặt API Key", expanded=not bool(app.api_key)):
        api_col1, api_col2 = st.columns([3, 1])
        with api_col1:
            api_key = st.text_input("Google Gemini API Key", type="password", value=app.api_key if app.api_key else "")
        with api_col2:
            if st.button("Set API Key"):
                if app.set_api_key(api_key):
                    st.success("API Key đã được cài đặt thành công!")
                else:
                    st.error("Vui lòng nhập API Key.")
    
    # Model selection
    if 'use_flash_model' not in st.session_state:
        st.session_state.use_flash_model = False
    
    use_flash_model = st.checkbox("Sử dụng gemini-2.0-flash (nhanh hơn)", value=st.session_state.use_flash_model)
    if use_flash_model != st.session_state.use_flash_model:
        st.session_state.use_flash_model = use_flash_model
        if app.api_key:
            app.update_model(use_flash_model)
    
    # Split PDF checkbox
    split_large_pdfs = st.checkbox("Tách PDF lớn hơn 10 trang", value=True)
    
    # Hiển thị Hardware ID và trạng thái kích hoạt
    st.write(f"Hardware ID: {app.hardware_id}")
    is_activated = app.check_activation()
    if is_activated:
        st.success("Trạng thái: ĐÃ KÍCH HOẠT")
    else:
        st.error("Trạng thái: CHƯA KÍCH HOẠT")
    
    # Nút đăng xuất
    if st.sidebar.button("Đăng xuất"):
        st.session_state.logged_in = False
        st.session_state.username = ""
        st.experimental_rerun()
    
    # File upload section
    st.write("---")
    st.subheader("Upload File")
    
    if not is_activated:
        st.warning("Vui lòng kích hoạt ứng dụng để sử dụng tính năng này.")
        return
    
    upload_tab1, upload_tab2 = st.tabs(["Upload PDF/Image", "Kết quả"])
    
    with upload_tab1:
        file_option = st.radio("Chọn loại file", ["PDF", "Image"])
        
        if file_option == "PDF":
            uploaded_file = st.file_uploader("Upload PDF file", type=["pdf"])
            if uploaded_file is not None:
                if app.api_key:
                    success, message = app.process_pdf(uploaded_file, split_large_pdfs)
                    if success:
                        st.success(message)
                    else:
                        st.error(message)
                else:
                    st.warning("Vui lòng cài đặt API Key trước.")
        else:
            uploaded_file = st.file_uploader("Upload Image file", type=["png", "jpg", "jpeg"])
            if uploaded_file is not None:
                if app.api_key:
                    success, message = app.process_image(uploaded_file)
                    if success:
                        st.success(message)
                    else:
                        st.error(message)
                else:
                    st.warning("Vui lòng cài đặt API Key trước.")
        
        col1, col2 = st.columns(2)
        
        with col1:
            convert_button = st.button("Convert to Text", disabled=not (app.api_key and (app.uploaded_file is not None or app.split_files)))
        
        with col2:
            latex_button = st.button("Convert to LaTeX", disabled=not (app.api_key and (app.uploaded_file is not None or app.split_files)))
    
    with upload_tab2:
        if convert_button and app.api_key:
            success, result = app.convert_pdf_to_text(is_latex_mcq=False)
            if success:
                st.session_state.conversion_result = result
                st.success("Đã chuyển đổi thành công!")
            else:
                st.error(result)
        
        if latex_button and app.api_key:
            success, result = app.convert_pdf_to_text(is_latex_mcq=True)
            if success:
                st.session_state.conversion_result = result
                st.success("Đã chuyển đổi thành LaTeX thành công!")
            else:
                st.error(result)
        
        if 'conversion_result' in st.session_state:
            st.text_area("Kết quả chuyển đổi:", value=st.session_state.conversion_result, height=500)
            if st.download_button(
                label="Tải về kết quả",
                data=st.session_state.conversion_result,
                file_name="conversion_result.txt",
                mime="text/plain"
            ):
                st.success("Đã tải về thành công!")

def main():
    st.set_page_config(page_title="P_Convert - PDF/Image to Text Converter", layout="wide")
    
    # Kiểm tra đăng nhập
    if not st.session_state.logged_in:
        login_page()
    else:
        main_app()

if __name__ == "__main__":
    main()
