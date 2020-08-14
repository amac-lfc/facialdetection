import tensorflow as tf
tf.compat.v1.logging.set_verbosity(tf.compat.v1.logging.ERROR)
from os import environ
environ['TF_CPP_MIN_LOG_LEVEL']='3'


import cv2 
import pickle 
import numpy as np
from mtcnn import MTCNN
from models import embeddingsPredictor
from sklearn.linear_model import LogisticRegression
from tensorflow.keras.applications.imagenet_utils import preprocess_input

class FaceRecognitionSystem(object):
    
    """
    ### Description
        Face Recognition System creates an instance of the class with the following capabilities:
        1. Face Detection with detectFaces, faceLocations, facialFeatures functions.
        2. Face Features extraction with faceEmbeddings functions.
        3. Face alignment for better face recognition.
        4. Faces comparison with faceDistance and compareFaces.
        5. Add face to database through camera
        6. Add face to database from file (can use folder loop to add multiple faces at once)
        
        Face Recognition relies on two pickle files:
        1. pickle file containing dictionary {id : name} of known faces.
        2. pickle file containing dictionary {id : listOfEmbeddings} of known faces.
        
    """
    FACE_CLASSIFIER = "/Users/newuser/Projects/facialdetection/FaceRecognition/custom/util/face_classifier.pkl"
    
    def __init__(self, 
                 face_size, # size of the face after transformation
                 names_pkl, # path to pickle file containing dictionary of known people
                 embeddings_pkl): # path to pickle file containing dictionary of known face embeddings
        """
        ### Description
            1. Initializes MTCNN Face detection model.
            2. Initializes FaceNet or VGGFace model to extract embeddings from face images.
            3. Connects to Database through DatabaseConnection class.
            4. assigns to instance variable a dictionary {id : name} of  known faces from the database.
            5. assigns to instance variable a dictionary {id : listOfEmbeddings} of known faces from the database.
            6. assingns to instance variable the desired face size required for the embeddings model.

        ### Args:
            'face_size' (int): face size required for the embeddings model e.g 160.
            'names_pkl' (str): path to pickle file containing dictionary {id : name} of known faces.
            'embeddings_pkl' (str):  path to pickle file containing dictionary {id : listOfEmbeddings} of known faces.
            
        """

        self.detector = MTCNN()
        self.predictor = embeddingsPredictor()
        self.connection = DatabaseConnection(db_file=names_pkl, embeddings_file=embeddings_pkl)
        self.db = self.connection.db
        self.embeddings = self.connection.embeddings
        self.face_size = face_size
    
    def alignCropFace(self, 
                      image, 
                      face_size=None,
                      face_location=None, 
                      facial_features=None):
        """
        This function take an image containing face, 
        aligns the face so that eyes are horizontal,
        and crops to given face size dimension.

        ## Args:
                image (array): array of pixels
                'face_size' (int): face size in terms of pixels e.g. 160
                'face_location' (tuple): tuple consisting of face location coordinates on image (x, y, width, height)
                'facial_features' (dict): "dictionary of facial features i.e. left and right eye coordinates"
                

        ## Returns:
                numpy array: transformed face image with shape (h, w, 3)
        """
        if face_size is None:
            face_size = self.face_size
            
        if facial_features is None:
            facial_features = self.facialFeatures(image)[0]

        if face_location is None:
            (x1, y1, width, height) = (0, 0, image.shape[1], image.shape[0])
        else:
            (x1, y1, width, height) = face_location

        left_eye_center = facial_features['left_eye']
        right_eye_center = facial_features['right_eye']
        left_eye_center = np.array(left_eye_center).astype("int")
        right_eye_center = np.array(right_eye_center).astype("int")

        # find angle of the line passing through eyes centers
        dY = right_eye_center[1] - left_eye_center[1]
        dX = right_eye_center[0] - left_eye_center[0]
        angle = np.degrees(np.arctan2(dY, dX))

        # to get the face at the center of the image
        desired_left_eye=(0.35, 0.35) 
        desired_right_eye_x = 1.0 - desired_left_eye[0] 

        desired_face_width = face_size
        desired_face_height = face_size

        # determine the scale of the new resulting image by taking
        # the ratio of the distance between eyes in the *current*
        # image to the ratio of distance between eyes in the
        # *desired* image
        dist = np.sqrt((dX ** 2) + (dY ** 2))
        desiredDist = (desired_right_eye_x - desired_left_eye[0])
        desiredDist *= desired_face_width

        if image.shape[1] >= 1000 or image.shape[0] >= 1000:
            scale = (desiredDist / dist) + 0.1
        elif (image.shape[1] > 300 or image.shape[0] > 300) and (image.shape[1] < 1000 or image.shape[0] < 1000):
            scale = (desiredDist / dist) + 0.2
        else:
            scale = (desiredDist / dist) + 0.35

        # compute center (x, y)-coordinates (i.e., the median point)
        # between the two eyes in the input image
        eyes_center = ((left_eye_center[0] + right_eye_center[0]) // 2,
                       (left_eye_center[1] + right_eye_center[1]) // 2)

        # grab the rotation matrix for rotating and scaling the face
        M = cv2.getRotationMatrix2D(eyes_center, angle, scale)

        # update the translation component of the matrix
        tX = desired_face_width * 0.5
        tY = desired_face_height * desired_left_eye[1]
        M[0, 2] += (tX - eyes_center[0])
        M[1, 2] += (tY - eyes_center[1])

        # apply the affine transformation
        (w, h) = (desired_face_width, desired_face_height)          
        output = cv2.warpAffine(image, 
                                M, 
                                (w, h), 
                                flags=cv2.INTER_CUBIC)
    
        return output
    
    def faceEmbeddings(self, 
                       image, 
                       face_locations=None, 
                       facial_features=None):
        """
        ### Description
            Given image containing faces, returns a list of found face embeddings.

        ### Args:
            image (nparray): image to extract features from
            'face_locations' (list, optional): list of face locations on the image. Defaults to None.
            facial_features (list, optional): list of facial features coordinates on the image. Defaults to None.

        ### Raises:
            ValueError: if a face size is not 160 or 224 

        ### Returns:
            list: list of extracted face embeddings
        """
        
        if face_locations is None or facial_features is None:
            face_locations, facial_features = self.detectFaces(image)
        
        def preprocess(img):
            img_gray = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
            img_rgb = np.repeat(img_gray[..., np.newaxis], 3, -1)
            
            if self.face_size == 160:
                mean, std = img_rgb.mean(), img_rgb.std()
                img_rgb = (img_rgb - mean) / std
            elif self.face_size == 224:
                img_rgb = preprocess_input(img_rgb)
            else:
                raise ValueError("Inappropriate value for face_size, please choose 160 or 224.")
            
            return img_rgb
        
        aligned_list = []
        for i, face_loc in enumerate(face_locations):
            aligned_face = self.alignCropFace(image, 
                                              face_location=face_loc, 
                                              facial_features=facial_features[i])
            preprocessed = preprocess(aligned_face)
            aligned_list.append(preprocessed)

        aligned_list = np.array(aligned_list)
        embeddings = np.array(self.predictor(aligned_list))
        
        return embeddings
        
    def detectFaces(self, image):
        
        """
        ### Description:
            Finds faces on a given image array and 
            returns list of location coordinates and 
            facial features coordinates.

        ### Returns:
            (list): list of face location bounding box coordinates
            (list): list of facial features dictionaries
            
        ```python
            
        boxes = [ (x1, y1, w1, h1), (x2, y2, w2, h2), ...]
        features = [
                     {
                        "left_eye" : (x1, y1),
                        "right_eye" : (x1, y1),
                        "nose" : (x1, y1)
                     },
                     {   
                        ...
                     }
                   ]```
        """
        faces = self.detector.detect_faces(image)
        bboxes = [] # face locations coordinates
        features = [] # facial features coordinates

        for face in faces:
            bboxes.append(face["box"])
            features.append({ "left_eye": face["keypoints"]["left_eye"],
                            "right_eye": face["keypoints"]["right_eye"],
                            "nose": face["keypoints"]["nose"] })

        return bboxes, features

    def faceLocations(self, image):
        faces = self.detector.detect_faces(image)
        return [face["box"] for face in faces]

    def facialFeatures(self, image):
        faces = self.detector.detect_faces(image)

        return [{ "left_eye": face["keypoints"]["left_eye"],
                "right_eye": face["keypoints"]["right_eye"],
                "nose": face["keypoints"]["nose"] } for face in faces]
    
    @staticmethod    
    def faceDistance(face_to_compare, 
                     face_embeddings, 
                     distance="euclidian"):
        """
        ### Description
            Given a list of known face embeddings, 
            compare them to a face embedding and get a euclidean or cosine distance
            for each comparison face. The distance tells you how similar the faces are.

        ### Args:
            'face_to_compare' (nparray): array containing unknown face embedding.
            'face_embeddings' (nparray, optional): array containing known face embeddings. Defaults to None.
            distance (str, optional): options: 'cosine', 'euclidian'. Defaults to "euclidian".
            
        ### Returns
            A numpy ndarray with the distance for each face in the same order as the 'face_embeddings' array.
        
        """

        # Computes cosine distance between two face embeddings
        def findCosineScore(source_representation, test_representation):
            a = np.matmul(np.transpose(source_representation), test_representation)
            b = np.sum(np.multiply(source_representation, source_representation))
            c = np.sum(np.multiply(test_representation, test_representation))
            return 1 - (a / (np.sqrt(b) * np.sqrt(c)))
        
        if len(face_embeddings) == 0:
            return np.empty((0))

        if distance == "euclidian":
            return np.linalg.norm(face_embeddings - face_to_compare, axis=1)
        elif distance == "cosine":
            return np.array([findCosineScore(face_embedding, face_to_compare) for face_embedding in face_embeddings])
        else:
            raise AttributeError("wrong distance attribute. Choose 'euc' or 'cosine'")
    
    @staticmethod
    def compareFaces(face_embedding_to_check, 
                     known_face_embeddings, 
                     distances=None, 
                     threshold=9):
        """
        ### Description
            Compare a list of known face embeddings 
            against a candidate embedding to see if they match.
        
        ### Args:
            'face_embedding_to_check' (nparray): array containing unknown face embedding 
            'known_face_embeddings' (nparray, optional): array containing known face embeddings. Defaults to None.
            distances (nparray, optional): list of known face distances if computed with faceDistance function. Defaults to None.
            threshold (int, optional): threshold of matching person. Defaults to 9.

        ### Returns:
            A list of True/False values indicating which known_face_embeddings match the face embedding to check
        """
        
        if distances is None:
            return list(FaceRecognitionSystem.faceDistance(face_embedding_to_check, known_face_embeddings) <= threshold)
        else:
            return list(distances <= threshold)
    
    def getEmbeddingsList(self):
        """
        ### Decription: 
            Given dictionary of embeddings return two lists 
            one containing ids of known people and the other containing face embeddings
            
        ```python
            dict = {
                1 : [ [embedding1], [embedding2], [embeddingN] ]
                2 : [ [embedding1], [embedding2], [embeddingN] ]
                3 : [ [embedding1], [embedding2], [embeddingN] ]
            }
            
            returns 
            embeddings_list = [ [embedding1], [embedding2], [embedding3], [embeddingN] ]
            id_list = [1, 1, 1, 1, 1, 2, 2, 2, ...]
        ```   
        ### Args
            embeddings (dict, optional): dictionary where keys are ids of known people and values are their embeddings. Defaults to None.

        ### Returns:  
            two lists with all ids and embeddings.
        """
        embeddings = self.embeddings 
        
        embeddings_list = []  # known face embeddings
        id_list = []	   # unique ids of known face embeddings


        for ref_id , embed_list in embeddings.items():
            if len(embed_list) > 1:
                for e in embed_list:
                    embeddings_list.append(e)
                    id_list.append(ref_id)
            else:
                embeddings_list.append(embed_list[0])
                id_list.append(ref_id)
       
        return embeddings_list, id_list
    
    def faceClassifier(self, path=None):
        """
        ### Description 
            Loads face classifier if serialized model file exists, 
            else trains a face classifier and returns it.

        ### Returns:
            clf: sklearn model object
        """
        #if path is None:
              
        try:
            with open(self.FACE_CLASSIFIER, 'rb') as f:
                clf = pickle.load(f)
        except:  
            X, y = self.getEmbeddingsList()
            X = np.array(X)
            print("Training face classifier...")
            clf = LogisticRegression().fit(X, y)  
            with open(self.FACE_CLASSIFIER, 'wb') as f:
                pickle.dump(clf, f)
        
        return clf
        
    def addEmbeddingsFromFile(self, filename, name):
        """
        ### Description
            Adds new face embeddings containing extracted features from a given image. 
            Creates a unique id in database based on given name.
            
        ### Args:
            filename (str): path to image.
            name (str): name of person on image.
        """

        image = cv2.cvtColor(cv2.imread(filename), cv2.COLOR_BGR2RGB)
        face_locations, facial_features = self.detectFaces(image)

        if facial_features:
            
            ref_id = self.connection.generateFaceID(name)

            face_embedding = self.faceEmbeddings(image, 
                                                 face_locations=face_locations, 
                                                 facial_features=facial_features)[0]

            if ref_id in self.embeddings.keys():
                self.embeddings[ref_id]+=[face_embedding]
            else:
                self.embeddings[ref_id]=[face_embedding]

           
            self.connection.dumpEmbeddings()
        else:
            print("No faces detected in the given image.")
    
    def addEmbeddingsFromCamera(self, name):
        """
        ### Description
            Using webcam adds new face embeddings containing extracted features to database. 
            Creates a unique id in database based on given name.
            
        ### Args:
            name (str): name of person on image.
        """

        how_many = int(input("How many embeddings would you like to add?\n"))
        
        while how_many not in range(1, 6):
            how_many = int(input("Sorry, you can add only 5 embeddings at max. How many embeddings would you like to add?\n"))

        for _ in range(how_many):

            key = cv2.waitKey(1)
            webcam = cv2.VideoCapture(0)

            while webcam.isOpened():
                check, frame = webcam.read()
                cv2.imshow("Capturing", frame) # Display frame
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB) # convert the frame from BGR (OpenCV) to RGB 
                
                key = cv2.waitKey(1)

                if key == 13: # ENTER key pressed
                    face_locations, facial_features = self.detectFaces(rgb_frame)
                    
                    if face_locations:

                        ref_id = self.connection.generateFaceID(name)
                        face_embedding = self.faceEmbeddings(rgb_frame, 
                                                             face_locations=face_locations, 
                                                             facial_features=facial_features)[0]

                        if ref_id in self.embeddings.keys():
                            self.embeddings[ref_id]+=[face_embedding]
                        else:
                            self.embeddings[ref_id]=[face_embedding]

                        webcam.release()
                        cv2.waitKey(1)
                        cv2.destroyAllWindows()     
                        break
                    else:
                        print("No faces detected. Make sure the face is visible.")
                        break

                elif key == 27: # ESC pressed
                    webcam.release()
                    print("Camera off.")
                    cv2.destroyAllWindows()
                    break
                
            if 'face_embedding' in locals():
                self.connection.dumpEmbeddings()

            
    
class DatabaseConnection(object):
    """
    ### Description 
        This class creates a database object which has the following functionalities:
        1. Creation of two pickle files that represent the database.
        2. Unique id generation for known faces.
        3. Safe dumping of dictionary data into pickle files.
        
        The class is a helper class to the FaceRecognitionSystem class.
    """
        
    def __init__(self, 
                 db_file, 
                 embeddings_file):
        
        self.db_file = db_file
        self.embeddings_file = embeddings_file
        try:
            with open(self.db_file, "rb") as f:
                db = pickle.load(f)
                
            with open(self.embeddings_file, "rb") as f2:
                embeddings = pickle.load(f2)  
        except:
            print("No db file exists. Creating new one")
            db = {}
            embeddings = {}
            with open(self.db_file, "wb") as f:
                pickle.dump(db)
            
            with open(self.embeddings_file, "wb") as f2:
                pickle.dump(embeddings)
            
        self.db = db
        self.embeddings = embeddings
        
    def dumpEmbeddings(self):
        """
        ### Description
            updates database with new embeddings.
        """
        with open(self.embeddings_file, "wb") as f:
            pickle.dump(self.embeddings, f)
        print("Embeddings added to database.")

    def generateFaceID(self, name):
        """
        ### Description
            Given name of a person, checks for matches in database, 
            if match found, returns its id, 
            otherwise generates new id and returns it.

        ### Args:
            name (str): name of a person e.g. 'Steve Jobs'

        ### Returns:
            int: unique id belonging to given person's name
        """
     
        for known_id, known_name in self.db.items():
            if name == known_name:
                ref_id = known_id
                break
        else:
            if not self.db:
                ref_id = 1
            else:
                ref_id = max(self.db.keys()) + 1
            self.db[ref_id] = name
        
        
        with open(self.db_file, "wb") as f:
            pickle.dump(self.db, f)

        return ref_id