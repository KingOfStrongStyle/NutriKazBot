from aiogram.fsm.state import State, StatesGroup


class AdminState(StatesGroup):
    # ==================================================================
    # LEAD SOURCE — управление источниками лидов (воронками)
    # ==================================================================
    lead_source_menu = State()               
    add_lead_source_name = State()           
    add_lead_source_description = State()    
    update_lead_source_select = State()      
    update_lead_source_field = State()       
    update_lead_source_value = State()       
    delete_lead_source_select = State()

    # ==================================================================
    # MESSAGE SCHEDULE — планирование индивидуальных сообщений
    # ==================================================================
    message_schedule_menu = State()
    select_message_users = State()
    message_users_page = State()
    add_message_type = State() 
    add_message_text_direct = State()      
    add_message_user_id = State()            
    add_message_text = State()     
    add_message_image = State()
    add_message_file = State()
    add_message_video = State()         
    add_message_time = State()               
    update_message_select = State()          
    update_message_text = State()            
    delete_message_select = State()          

    # ==================================================================
    # BROADCAST — массовые рассылки
    # ==================================================================
    broadcast_menu = State()                 
    add_broadcast_lead_source = State()                          
    update_broadcast_select = State()        
    update_broadcast_text = State()         
    delete_broadcast_select = State()
    add_broadcast_type = State()            
    add_broadcast_text = State()            
    add_broadcast_image = State()           
    add_broadcast_file = State()          
    add_broadcast_video = State()
    add_broadcast_time = State()            
    
    user_menu = State()

    # ==================================================================
    # ТЕКСТЫ ЭТАПОВ — РЕДАКТИРОВАНИЕ
    # ==================================================================
    edit_stage_select = State()          
    edit_text_input = State()           
    edit_feedback_input = State()     
    
    
class LeadMagnetState(StatesGroup):
    feedback = State()
    purchase_interest = State()