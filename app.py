import streamlit as st
import os
import re
import platform
import hashlib
import requests
import tempfile
import io
from PIL import Image
from PyPDF2 import PdfReader, PdfWriter
import google.generativeai as genai

class PDFConverterApp:
    def __init__(self):
        self.api_key = ""
        self.file_path = None
        self.uploaded_file = None
        self.model = None
        self.pdf_text = ""
        self.split_files = []
        self.activation_status = "CHƯA KÍCH HOẠT"
        self.hardware_id = self.get_hardware_id()
        
    def get_hardware_id(self):
        # Simplified hardware ID for Streamlit Cloud - using session ID
        if 'session_id' not in st.session_state:
            st.session_state.session_id = hashlib.md5(str(os.urandom(24)).encode()).hexdigest().upper()
        
        # Format for display
        session_id = st.session_state.session_id
        formatted_id = '-'.join([session_id[i:i+8] for i in range(0, len(session_id), 8)])
        return formatted_id + "-Premium"

    def check_activation(self):
        try:
            url = "https://raw.githubusercontent.com/thayphuctoan/pconvert/main/check-convert"
            response = requests.get(url)
            if response.status_code == 200:
                valid_ids = response.text.strip().split('\n')
                if self.hardware_id in valid_ids:
                    self.activation_status = "ĐÃ KÍCH HOẠT"
                    return True
                else:
                    self.activation_status = "CHƯA KÍCH HOẠT"
                    return False
            else:
                self.activation_status = "CHƯA KÍCH HOẠT"
                return False
        except Exception as e:
            st.error(f"Error checking activation: {str(e)}")
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

def main():
    st.set_page_config(page_title="P_Convert - PDF/Image to Text Converter", layout="wide")
    
    st.title("P_Convert v1.3")
    st.subheader("Chuyển PDF/Image sang văn bản không lỗi công thức Toán")
    
    # Khởi tạo ứng dụng
    if 'app' not in st.session_state:
        st.session_state.app = PDFConverterApp()
    app = st.session_state.app
    
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
    
    # Hardware ID and Activation Status
    st.write(f"Hardware ID: {app.hardware_id}")
    is_activated = app.check_activation()
    if is_activated:
        st.success("Trạng thái: ĐÃ KÍCH HOẠT")
    else:
        st.error("Trạng thái: CHƯA KÍCH HOẠT")
    
    # File upload section
    st.write("---")
    st.subheader("Upload File")
    
    upload_tab1, upload_tab2 = st.tabs(["Upload PDF/Image", "Kết quả"])
    
    with upload_tab1:
        file_option = st.radio("Chọn loại file", ["PDF", "Image"])
        
        if file_option == "PDF":
            uploaded_file = st.file_uploader("Upload PDF file", type=["pdf"])
            if uploaded_file is not None:
                if app.api_key and is_activated:
                    success, message = app.process_pdf(uploaded_file, split_large_pdfs)
                    if success:
                        st.success(message)
                    else:
                        st.error(message)
                elif not app.api_key:
                    st.warning("Vui lòng cài đặt API Key trước.")
                else:
                    st.warning("Vui lòng kích hoạt ứng dụng để sử dụng tính năng này.")
        else:
            uploaded_file = st.file_uploader("Upload Image file", type=["png", "jpg", "jpeg"])
            if uploaded_file is not None:
                if app.api_key and is_activated:
                    success, message = app.process_image(uploaded_file)
                    if success:
                        st.success(message)
                    else:
                        st.error(message)
                elif not app.api_key:
                    st.warning("Vui lòng cài đặt API Key trước.")
                else:
                    st.warning("Vui lòng kích hoạt ứng dụng để sử dụng tính năng này.")
        
        col1, col2 = st.columns(2)
        
        with col1:
            convert_button = st.button("Convert to Text", disabled=not (app.api_key and is_activated and (app.uploaded_file is not None or app.split_files)))
        
        with col2:
            latex_button = st.button("Convert to LaTeX", disabled=not (app.api_key and is_activated and (app.uploaded_file is not None or app.split_files)))
    
    with upload_tab2:
        if convert_button and app.api_key and is_activated:
            success, result = app.convert_pdf_to_text(is_latex_mcq=False)
            if success:
                st.session_state.conversion_result = result
                st.success("Đã chuyển đổi thành công!")
            else:
                st.error(result)
        
        if latex_button and app.api_key and is_activated:
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

if __name__ == "__main__":
    main()
