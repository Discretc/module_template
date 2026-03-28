-- Seed data (v2) – sample faculties, programmes, and classes
-- Matches the new trilingual schema

INSERT INTO faculties (code, name_en, name_zh, name_pt) VALUES
    ('FCA', 'Faculty of Applied Sciences',              '應用科學學院',   'Faculdade de Ciências Aplicadas'),
    ('FCH', 'Faculty of Humanities and Social Sciences', '人文及社會科學學院', 'Faculdade de Humanidades e Ciências Sociais');

INSERT INTO programmes (code, name_en, name_zh, name_pt, degree_level, faculty_id) VALUES
    ('4LCSDI', 'Bachelor of Science in Computing',
        '電腦學理學士學位課程', 'Licenciatura em Ciências da Computação',
        'bachelor', 1),
    ('4LAIDI', 'Bachelor of Science in Artificial Intelligence',
        '人工智能理學士學位課程', 'Licenciatura em Inteligência Artificial',
        'bachelor', 1),
    ('MDATAM', 'Master of Science in Big Data and Internet of Things',
        '大數據與物聯網碩士學位課程', 'Mestrado em Big Data e Internet das Coisas',
        'master', 1),
    ('4LDSGN', 'Bachelor of Arts in Design',
        '設計學士學位課程', 'Licenciatura em Design',
        'bachelor', 2);

INSERT INTO classes (class_code, module_code, module_name_en, module_name_zh, module_name_pt,
    prerequisite_en, prerequisite_zh, prerequisite_pt, credits, duration,
    instructor_en, instructor_zh, instructor_pt, email, room_en, room_zh, room_pt, telephone,
    marking_rule, programme_id) VALUES
    ('COMP1123-121', 'COMP1123', 'Computer Organization', '計算機組織', 'Organização de Computadores',
        'Nil', '無', 'Nil', 3, 45,
        'CHAN Tai Man', '陳大文', 'CHAN Tai Man', 'tmchan@mpu.edu.mo',
        'M505', 'M505', 'M505', '8599-3275',
        3, 1),
    ('COMP1124-121', 'COMP1124', 'Advanced Programming', '高級程式設計', 'Programação Avançada',
        'COMP1121', 'COMP1121', 'COMP1121', 3, 45,
        'WONG Sio Kei', '黃兆基', 'WONG Sio Kei', 'skwong@mpu.edu.mo',
        'M503', 'M503', 'M503', '8599-3280',
        2, 1),
    ('COMP1123-124', 'COMP1123', 'Computer Organization', '計算機組織', 'Organização de Computadores',
        'Nil', '無', 'Nil', 3, 45,
        'LEI Ka Hou', '李家豪', 'LEI Ka Hou', 'khlei@mpu.edu.mo',
        'M506', 'M506', 'M506', '8599-3281',
        4, 2),
    ('MSBD5001-131', 'MSBD5001', 'Advanced Machine Learning', '高級機器學習', 'Aprendizagem Automática Avançada',
        'Nil', '無', 'Nil', 3, 45,
        'LEONG Hou U', '梁浩宇', 'LEONG Hou U', 'huleong@mpu.edu.mo',
        'M508', 'M508', 'M508', '8599-3290',
        1, 3),
    ('DSGN1101-211', 'DSGN1101', 'Fundamentals of Visual Design', '視覺設計基礎', 'Fundamentos do Design Visual',
        'Nil', '無', 'Nil', 3, 45,
        'HO Mei Leng', '何美玲', 'HO Mei Leng', 'mlho@mpu.edu.mo',
        'A301', 'A301', 'A301', '8599-6100',
        2, 4);
