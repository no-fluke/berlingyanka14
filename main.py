import os
import logging
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import requests
import aiohttp
import asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Bot configuration
BOT_TOKEN = os.getenv('BOT_TOKEN')
API_BASE_URL = "https://backend.multistreaming.site/api/courses"

class CourseExtractor:
    def __init__(self):
        self.courses_cache = {}
    
    async def get_courses_list(self):
        """Get list of available courses"""
        try:
            async with aiohttp.ClientSession() as session:
                # You might need to adjust this endpoint based on your API
                async with session.get(f"{API_BASE_URL}") as response:
                    if response.status == 200:
                        data = await response.json()
                        return data.get('data', [])
                    else:
                        logger.error(f"API returned status: {response.status}")
                        return []
        except Exception as e:
            logger.error(f"Error fetching courses: {e}")
            return []
    
    async def get_course_data(self, course_id):
        """Get detailed course data"""
        try:
            async with aiohttp.ClientSession() as session:
                url = f"{API_BASE_URL}/{course_id}/classes?populate=full"
                async with session.get(url) as response:
                    if response.status == 200:
                        return await response.json()
                    else:
                        logger.error(f"API returned status {response.status} for course {course_id}")
                        return None
        except Exception as e:
            logger.error(f"Error fetching course data: {e}")
            return None
    
    def generate_text_file(self, course_data, course_title):
        """Generate text file content in the required format"""
        if not course_data or 'data' not in course_data:
            return None
        
        content_lines = []
        
        # Process classes data
        classes_data = course_data['data'].get('classes', [])
        
        for topic in classes_data:
            topic_name = topic.get('topicName', 'Unknown Topic')
            classes_list = topic.get('classes', [])
            
            for class_item in classes_list:
                # Extract class information
                class_title = class_item.get('title', '')
                teacher_name = class_item.get('teacherName', '')
                
                # Get video URL (prefer MP4 recordings)
                video_url = ""
                mp4_recordings = class_item.get('mp4Recordings', [])
                if mp4_recordings:
                    # Try to get 720p first, then any available quality
                    for recording in mp4_recordings:
                        if recording.get('quality') == '720p':
                            video_url = recording.get('url', '')
                            break
                    if not video_url and mp4_recordings:
                        video_url = mp4_recordings[0].get('url', '')
                
                # If no MP4, try class_link
                if not video_url:
                    video_url = class_item.get('class_link', '')
                
                # Format the class line
                if video_url:
                    class_line = f"{class_title} | {teacher_name} | {topic_name} | ({teacher_name}): {video_url}"
                    content_lines.append(class_line)
                
                # Add PDFs
                class_pdfs = class_item.get('classPdf', [])
                for pdf in class_pdfs:
                    pdf_name = pdf.get('name', '')
                    pdf_url = pdf.get('url', '')
                    if pdf_name and pdf_url:
                        pdf_line = f"{pdf_name} ({teacher_name}): {pdf_url}"
                        content_lines.append(pdf_line)
        
        return "\n".join(content_lines)

# Initialize course extractor
extractor = CourseExtractor()

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send welcome message and show available batches"""
    welcome_text = """
🤖 *Course Extractor Bot*

I can help you extract course data and generate text files with video and PDF links.

Use /batches to see available batches and extract data.
    """
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def show_batches(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show available batches"""
    try:
        await update.message.reply_text("🔄 Fetching available batches...")
        
        # Get courses list
        courses = await extractor.get_courses_list()
        
        if not courses:
            await update.message.reply_text("❌ No batches available or API error.")
            return
        
        # Store courses in context for later use
        context.user_data['available_courses'] = courses
        
        # Create batches list message
        batches_text = "📚 *Available Batches:*\n\n"
        for i, course in enumerate(courses, 1):
            course_title = course.get('title', f'Batch {i}')
            course_id = course.get('id', '')
            batches_text += f"{i}. {course_title}\n"
        
        batches_text += "\nPlease reply with the number of the batch you want to extract."
        
        await update.message.reply_text(batches_text, parse_mode='Markdown')
        
    except Exception as e:
        logger.error(f"Error in show_batches: {e}")
        await update.message.reply_text("❌ Error fetching batches. Please try again.")

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle user messages"""
    try:
        user_input = update.message.text.strip()
        
        # Check if user is selecting a batch number
        if 'available_courses' in context.user_data:
            if user_input.isdigit():
                batch_number = int(user_input)
                courses = context.user_data['available_courses']
                
                if 1 <= batch_number <= len(courses):
                    selected_course = courses[batch_number - 1]
                    await extract_course_data(update, context, selected_course)
                else:
                    await update.message.reply_text("❌ Invalid batch number. Please select from the list.")
            else:
                await update.message.reply_text("❌ Please enter a valid number.")
        else:
            await update.message.reply_text("ℹ️ Use /batches to see available batches first.")
            
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")
        await update.message.reply_text("❌ An error occurred. Please try again.")

async def extract_course_data(update: Update, context: ContextTypes.DEFAULT_TYPE, course):
    """Extract course data and send text file"""
    try:
        course_id = course.get('id')
        course_title = course.get('title', f'Batch_{course_id}')
        
        await update.message.reply_text(f"🔄 Extracting data for: {course_title}")
        
        # Get course data
        course_data = await extractor.get_course_data(course_id)
        
        if not course_data:
            await update.message.reply_text("❌ Failed to fetch course data.")
            return
        
        # Generate text file content
        text_content = extractor.generate_text_file(course_data, course_title)
        
        if not text_content:
            await update.message.reply_text("❌ No data found for this batch.")
            return
        
        # Create filename
        filename = f"{course_title.replace(' ', '_')}.txt"
        
        # Send as text file
        await update.message.reply_document(
            document=text_content.encode('utf-8'),
            filename=filename,
            caption=f"📁 {course_title} - Extracted Data"
        )
        
        # Clear the courses cache
        if 'available_courses' in context.user_data:
            del context.user_data['available_courses']
            
    except Exception as e:
        logger.error(f"Error in extract_course_data: {e}")
        await update.message.reply_text("❌ Error extracting course data.")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")
    if update and update.message:
        await update.message.reply_text("❌ An error occurred. Please try again.")

def main():
    """Start the bot"""
    if not BOT_TOKEN:
        logger.error("BOT_TOKEN environment variable is required!")
        return
    
    # Create application
    application = Application.builder().token(BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("batches", show_batches))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    application.add_error_handler(error_handler)
    
    # Start bot
    logger.info("Bot is starting...")
    application.run_polling()

if __name__ == '__main__':
    main()
