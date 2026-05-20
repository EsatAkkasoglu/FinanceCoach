import { initializeApp } from "firebase/app";
import { getAuth, GoogleAuthProvider } from "firebase/auth";

const firebaseConfig = {
  apiKey: "AIzaSyDTM8WJ_e0XkE0vcBPQwD7QFUowoG2hE1E",
  authDomain: "fincoach-esat.web.app",
  projectId: "fincoach-esat",
  storageBucket: "fincoach-esat.firebasestorage.app",
  messagingSenderId: "231143485349",
  appId: "1:231143485349:web:188cefb58abbbe4c99824c",
};

export const firebaseApp = initializeApp(firebaseConfig);
export const auth = getAuth(firebaseApp);
export const googleProvider = new GoogleAuthProvider();
