-- Seed data – sample programmes and modules
-- Based on the PDF example and realistic MPU data

INSERT INTO programmes (programme_name, degree_level, academic_unit) VALUES
    ('Bachelor of Science in Computing',            'Bachelor''s', 'Faculty of Applied Sciences'),
    ('Master of Science in Big Data and IoT',       'Master''s',   'Faculty of Applied Sciences'),
    ('Bachelor of Arts in Design',                  'Bachelor''s', 'Faculty of Humanities and Social Sciences'),
    ('Doctoral Programme in Computer Science',      'Doctoral',    'Faculty of Applied Sciences');

-- Modules linked to the programmes above (programme_id matches insertion order)
INSERT INTO modules (module_code, module_name, programme_id, prerequisites, medium_of_instruction, credits, contact_hours) VALUES
    -- Programme 1: BSc Computing
    ('MSEL3101', 'Introduction to Psychology',          1, 'Nil',                      'English',    3, '45 hrs'),
    ('COMP1121', 'Programming Fundamentals',            1, 'Nil',                      'English',    3, '45 hrs'),
    ('COMP2201', 'Data Structures and Algorithms',      1, 'COMP1121',                 'English',    3, '45 hrs'),
    ('COMP2202', 'Database Systems',                    1, 'COMP1121',                 'English',    3, '45 hrs'),
    ('COMP3301', 'Software Engineering',                1, 'COMP2201, COMP2202',       'English',    3, '45 hrs'),
    ('COMP3302', 'Computer Networks and Security',      1, 'COMP2201',                 'English',    3, '45 hrs'),
    ('COMP4401', 'Final Year Project',                  1, 'COMP3301',                 'English',    6, '90 hrs'),

    -- Programme 2: MSc Big Data and IoT
    ('MSBD5001', 'Advanced Machine Learning',           2, 'Nil',                      'English',    3, '45 hrs'),
    ('MSBD5002', 'IoT Systems Architecture',            2, 'Nil',                      'English',    3, '45 hrs'),

    -- Programme 3: BA Design
    ('DSGN1101', 'Fundamentals of Visual Design',       3, 'Nil',                      'English',    3, '45 hrs'),
    ('DSGN2201', 'Typography and Layout',               3, 'DSGN1101',                 'English',    3, '45 hrs'),

    -- Programme 4: Doctoral CS
    ('CSCI9001', 'Research Methods in Computer Science', 4, 'Nil',                     'English',    3, '45 hrs');
